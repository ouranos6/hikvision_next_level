# Phase 2 — Event Architecture Refactor

Tu travailles dans le dépôt `hikvision_next_level`.

Avant toute modification, lis intégralement :

* `PROJECT_REFERENCE.md`
* `AUDIT_PHASE_0.md`
* `PHASE_1_REPORT.md`

La Phase 1 a établi la baseline de compatibilité Home Assistant.

Ne remets pas en cause les décisions de Phase 1 sauf si un bug concret est découvert.

---

# Objectif

Refactorer le système d’événements Hikvision afin de séparer clairement :

```text
transport HTTP
→ extraction payload
→ parsing Hikvision
→ normalisation événement
→ résolution device/channel
→ mise à jour Home Assistant
```

Cette phase doit conserver exactement le comportement fonctionnel actuel.

Elle prépare la Phase 3, où sera ajouté le listener HTTP legacy compatible avec les requêtes Hikvision sans `Host`.

---

# Contraintes principales

Dans cette phase :

NE PAS :

* créer le listener raw TCP ;
* utiliser `asyncio.start_server`;
* monkey-patcher aiohttp ;
* ajouter Human / Vehicle entities ;
* ajouter event images côté HA ;
* ajouter PTZ ;
* ajouter capabilities ;
* modifier les unique IDs ;
* modifier les entity IDs ;
* modifier le domain ;
* modifier le comportement NVR visible ;
* ajouter de nouvelles fonctionnalités utilisateur.

Le résultat attendu est principalement architectural.

---

# 1. Commencer par analyser le chemin événement actuel

À partir du code réel, confirmer les responsabilités actuelles :

```text
EventNotificationsView.post
    |
    +-- lecture requête
    |
    +-- parse_event_request
    |
    +-- ISAPIClient.parse_event_notification
    |
    +-- get_isapi_device / channel mapping
    |
    +-- update_alert_channel
    |
    +-- binary sensor update
    |
    +-- HA event fire
```

Documenter toute différence réelle avant modification.

---

# 2. Objectif architectural

La cible doit devenir conceptuellement :

```text
Transport
   |
   v
Raw Hikvision payload
   |
   v
Event Parser
   |
   v
Normalized HikvisionEvent
   |
   v
Event Processor / Manager
   |
   +-- resolve device
   +-- resolve channel
   +-- update binary sensor
   +-- fire HA event
```

Le transport ne doit pas connaître les détails du traitement métier.

Le parser ne doit pas mettre à jour Home Assistant.

Le processor ne doit pas dépendre d’un objet `aiohttp.web.Request`.

---

# 3. Introduire un modèle événement normalisé

Créer une représentation interne typée.

Par exemple :

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class HikvisionEvent:
    event_type: str
    event_state: str | None

    channel_id: int | str | None

    device_serial: str | None
    device_mac: str | None
    device_ip: str | None

    target_type: str | None
    region_id: int | str | None

    timestamp: datetime | None

    raw: dict | None = None
```

Ce modèle est indicatif.

Adapte-le aux données réellement disponibles dans le parser existant.

Ne rajoute pas des champs inventés uniquement parce qu’ils pourraient servir plus tard.

Mais prépare proprement la possibilité d’ajouter ultérieurement :

```text
image
target classification
event metadata
```

sans casser l’architecture.

---

# 4. Séparer parsing HTTP et parsing Hikvision

Aujourd’hui :

```python
parse_event_request(request)
```

mélange probablement :

* lecture body ;
* inspection Content-Type ;
* multipart ;
* extraction XML.

Extraire cette logique dans un parser indépendant.

Conceptuellement :

```python
class HikvisionEventPayloadParser:
    def parse(
        self,
        body: bytes,
        content_type: str | None,
    ) -> ParsedPayload:
        ...
```

Le parser ne doit pas prendre :

```python
aiohttp.web.Request
```

en argument.

Le transport doit fournir :

```text
body bytes
content type
éventuellement headers utiles
source IP
```

au parser.

---

# 5. Introduire ParsedEventPayload si nécessaire

Si cela rend le code plus propre, créer :

```python
@dataclass(slots=True)
class ParsedEventPayload:
    xml: str
    image: bytes | None = None
```

Même si la Phase 2 ne doit pas encore exposer les JPEG aux entités HA.

Important :

Si un multipart contient déjà un JPEG :

NE PAS le jeter volontairement dans la nouvelle architecture.

Le conserver dans la structure interne si cela peut être fait proprement.

Mais :

NE PAS encore créer :

```text
image.<camera>_last_event
```

Cela appartient à une phase ultérieure.

---

# 6. Parser XML

Analyser :

```text
ISAPIClient.parse_event_notification
```

et déterminer si cette méthode doit :

A. rester dans `ISAPIClient`

ou

B. être déplacée dans le nouveau module événement.

Préférer la séparation logique.

Le client ISAPI doit idéalement gérer :

```text
requêtes ISAPI
authentification
XML request/response ISAPI
```

Le parsing d’un event notification est plutôt une responsabilité du moteur d’événements.

Mais ne fais ce déplacement que si cela réduit réellement le couplage.

---

# 7. Normalisation événement

Le XML Hikvision peut contenir différentes formes :

```text
eventType
eventState
channelID
dynChannelID
serialNumber
macAddress
ipAddress
DetectionRegionList
detectionTarget
```

ou d’autres structures selon firmware.

Créer une normalisation centrale.

Le reste de l’intégration ne doit plus avoir besoin de connaître directement les chemins XML.

Par exemple :

```python
event.event_type
event.channel_id
event.device_serial
event.target_type
```

---

# 8. Ne pas casser les événements existants

Les événements actuels Home Assistant doivent rester identiques.

Si l’intégration fait actuellement :

```python
hass.bus.async_fire(...)
```

avec certaines clés :

préserver :

* nom de l’événement HA ;
* noms des champs ;
* type des valeurs lorsque possible.

Ne renomme rien dans cette phase.

Créer une couche de conversion :

```text
HikvisionEvent
→ existing HA event payload
```

si nécessaire.

---

# 9. Event Processor

Créer un composant distinct chargé de :

```text
normalized HikvisionEvent
      |
      +-- find Hikvision device
      |
      +-- map NVR channel
      |
      +-- update alert state
      |
      +-- update binary sensor
      |
      +-- fire Home Assistant event
```

Conceptuellement :

```python
class HikvisionEventProcessor:

    async def async_process(
        self,
        event: HikvisionEvent,
        source_ip: str | None = None,
    ) -> None:
        ...
```

Le processor peut utiliser :

```text
hass
device list / runtime information
```

car cette couche appartient à l’intégration HA.

Mais il ne doit pas dépendre de :

```text
aiohttp.web.Request
MultipartDecoder
HTTP headers
```

---

# 10. Device resolution

Conserver la logique fonctionnelle de Phase 1.

Elle peut utiliser :

1. serial ;
2. MAC ;
3. source IP ;
4. hostname resolution si nécessaire.

Ne réintroduis pas :

```python
self.device
```

sur un objet partagé.

Chaque événement doit être traité avec son propre contexte.

La résolution hostname doit continuer à passer par :

```python
hass.async_add_executor_job(...)
```

ou l’API HA appropriée utilisée en Phase 1.

---

# 11. NVR channel mapping

Ne change pas le mapping des channels.

Conserver notamment :

```text
NVR event
→ channel ID
→ camera proxy / child device
→ binary sensor
```

Créer éventuellement une méthode dédiée :

```python
resolve_event_channel(...)
```

si cela permet de retirer cette logique du transport HTTP.

Les tests NVR Phase 1 doivent toujours passer.

---

# 12. Transport HTTP actuel

À la fin de Phase 2 :

```text
EventNotificationsView
```

doit devenir très mince.

Conceptuellement :

```python
async def post(self, request):
    body = await request.read()

    parsed_payload = parser.parse(
        body=body,
        content_type=request.headers.get("Content-Type"),
    )

    event = event_parser.parse(parsed_payload.xml)

    await processor.async_process(
        event,
        source_ip=request.remote,
    )

    return web.Response(...)
```

Adapte la structure exacte au code.

Le principe important est :

```text
HTTP view ≠ business logic
```

---

# 13. Content-Type

Dans cette phase, rendre le parser suffisamment indépendant pour supporter facilement les futurs Content-Type Hikvision.

Si cela peut être fait sans introduire la logique Phase 3, accepte proprement :

```text
application/xml
text/xml
multipart/*
```

Pour :

```text
application/x-www-form-urlencoded
```

deux options sont acceptables :

A. ajouter dès maintenant un fallback XML sniffing si isolé et testé ;

ou

B. préserver le comportement actuel et préparer le parser pour le correctif Phase 3.

Préférer A si le changement est petit, sûr et bien testé.

Exemple de principe :

```python
if body.lstrip().startswith(b"<?xml") or b"<EventNotificationAlert" in body:
    treat_as_xml()
```

Ne dépends jamais uniquement du Content-Type Hikvision.

---

# 14. Multipart

Centraliser le parsing multipart.

Le parser doit être capable d’identifier :

```text
XML part
JPEG part
```

Ne suppose pas que l’ordre est toujours :

```text
XML puis JPEG
```

Ne suppose pas que tous les firmwares utilisent exactement :

```text
application/xml
image/jpeg
```

Utilise MIME + content sniffing raisonnable.

Ne transforme pas les images.

Ne les écrit pas sur disque.

---

# 15. HTTP Host bug

NE PAS essayer de le corriger dans cette phase.

Le problème :

```text
Missing 'Host' header
```

est rejeté avant :

```text
EventNotificationsView.post
```

La nouvelle architecture doit simplement permettre à un futur transport raw de faire :

```text
raw listener
    |
    +-- body
    +-- content_type
    +-- source_ip
            |
            v
same parser
            |
            v
same processor
```

C’est le critère architectural principal de cette phase.

---

# 16. Nouveau découpage fichiers

Ne crée pas nécessairement une arborescence excessive.

Une structure acceptable pourrait être :

```text
custom_components/hikvision_next/

notifications.py

events/
    __init__.py
    models.py
    parser.py
    processor.py
```

ou une structure proche.

Le but est la séparation des responsabilités, pas le nombre de fichiers.

Évite les fichiers de 20 lignes inutiles.

---

# 17. Tests obligatoires

Les tests suivants doivent être ajoutés.

## XML simple

```text
application/xml
→ XML parsed
→ normalized event
```

## text/xml

```text
text/xml
→ parsed
```

## multipart XML

```text
multipart
→ XML extracted
```

## multipart XML + JPEG

```text
multipart
→ XML extracted
→ JPEG retained internally
```

## Wrong MIME with XML

Si le fallback est ajouté :

```text
application/x-www-form-urlencoded
+
XML body
→ XML detected
```

## malformed event

```text
invalid XML
→ controlled parser error
```

Pas de crash non géré.

---

# 18. Normalized event tests

Ajouter des fixtures réelles ou réalistes pour :

```text
motion
line crossing
intrusion
```

Tester que le normalized event contient correctement les données disponibles.

Si `detectionTarget` existe déjà :

tester au minimum :

```text
human
vehicle
```

mais NE PAS encore créer de nouveaux binary sensors.

Le but est seulement de vérifier que l’information n’est pas perdue.

---

# 19. Processor tests

Tester :

```text
normalized event
→ correct device
```

et :

```text
NVR event
→ correct child camera/channel
```

Puis vérifier :

```text
binary sensor update
HA event fire
```

avec le même comportement qu’avant le refactor.

---

# 20. Lifecycle tests

Tous les tests Phase 1 doivent continuer à passer.

Particulièrement :

```text
setup
→ unload
→ setup
```

et :

```text
HTTP view registered once
```

Le nouveau parser/processor ne doit pas créer de listener supplémentaire au setup des config entries.

---

# 21. Exceptions

Créer des exceptions événement explicites si utile.

Par exemple :

```python
class HikvisionEventParseError(Exception):
    pass
```

ou :

```python
class UnsupportedEventPayloadError(...):
```

Évite les :

```python
except Exception:
```

massifs sauf frontière défensive appropriée.

Le transport peut convertir une erreur parser en HTTP 400 ou log contrôlé.

---

# 22. Logging

Ajouter DEBUG utile :

```text
event content type
payload length
event type
channel
target
```

Ne jamais logguer :

```text
JPEG bytes
credentials
Authorization headers
```

En erreur XML :

ne logguer qu’un extrait raisonnable si réellement utile.

---

# 23. Type safety

Ajouter des types aux nouvelles structures.

Éviter :

```python
dict[str, Any]
```

partout lorsque le modèle est connu.

Mais ne refactore pas tout le dépôt dans cette phase.

---

# 24. Backwards compatibility

Vérifier explicitement que cette phase ne modifie pas :

```text
domain
config entries
unique IDs
entity IDs
device registry identifiers
entity names
existing service names
HA event name
existing HA event payload keys
```

Si un changement est absolument nécessaire :

documenter avant de l’effectuer.

---

# 25. Tests environnement

La Phase 1 n’a pas pu exécuter pytest à cause de la stack de dépendances.

Réévaluer l’environnement.

Avant de modifier les requirements :

identifier exactement :

```text
pytest-homeassistant-custom-component version
Home Assistant version
pytest version
pytest-cov version
Python version
```

Si nécessaire, proposer une combinaison de dépendances cohérente.

Ne modifie pas `requirements.test.txt` silencieusement.

Si une correction de pinning est clairement nécessaire :

documente la raison dans le rapport.

Priorité :

obtenir enfin une suite de tests exécutable.

---

# 26. Validation minimum

Exécuter au minimum :

```text
python -m compileall
git diff --check
```

et si l’environnement le permet :

```text
pytest
```

Si pytest reste impossible :

ne prétends pas que le refactor est validé intégralement.

Documente précisément le blocage.

---

# 27. Livrable

Créer :

```text
PHASE_2_REPORT.md
```

avec :

## Architecture before

Résumé de l’ancienne architecture événement.

## Architecture after

Décrire :

```text
transport
parser
normalized event
processor
```

## Files changed

Liste précise.

## Event model

Décrire les champs du modèle normalisé.

## Multipart handling

Expliquer comment XML/JPEG sont traités.

## NVR behavior

Confirmer qu’il est préservé.

## HA event compatibility

Confirmer :

```text
event name unchanged
payload keys unchanged
```

ou documenter toute différence.

## Tests added

Liste.

## Tests executed

Commandes + résultats exacts.

## Known limitations

Inclure obligatoirement :

```text
HTTP/1.1 requests without Host are still rejected by aiohttp.
This is intentionally deferred to Phase 3.
```

## Phase 3 readiness

Expliquer précisément comment le futur raw listener pourra appeler :

```text
parser
processor
```

sans dépendre d’aiohttp.

---

# 28. Git review

Avant de terminer :

```text
git status
git diff
git diff --check
```

Vérifier qu’aucun changement hors scope n’a été introduit.

---

# 29. Commit

Si approprié :

```text
refactor: separate Hikvision event transport and processing
```

Ne push rien sans instruction.

---

# 30. Critères d’acceptation

La Phase 2 est terminée uniquement si :

* transport séparé du parser ;
* parser indépendant d’aiohttp ;
* événement normalisé introduit ;
* processor indépendant du transport ;
* NVR mapping préservé ;
* existing HA event behavior préservé ;
* JPEG multipart non perdu si rencontré ;
* aucun raw listener créé ;
* aucun changement unique/entity ID ;
* tests nouveaux ajoutés ;
* Phase 1 lifecycle préservé ;
* `PHASE_2_REPORT.md` créé.

---

# 31. Arrêt obligatoire

À la fin :

```text
Phase 2 complete.

Event transport, parsing and processing are now separated.
See PHASE_2_REPORT.md

Deferred to Phase 3:
Legacy Hikvision HTTP listener for requests without Host header.
```

Puis arrête-toi.

N’entame pas la Phase 3.
