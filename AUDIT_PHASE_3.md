# Phase 3 — Legacy Hikvision HTTP Listener

Tu travailles dans le dépôt `hikvision_next_level`.

Avant toute modification, lis intégralement :

* `PROJECT_REFERENCE.md`
* `AUDIT_PHASE_0.md`
* `PHASE_1_REPORT.md`
* `PHASE_2_REPORT.md`

La Phase 2 a séparé :

```text
transport
→ payload parser
→ normalized HikvisionEvent
→ processor
```

Cette architecture doit être conservée.

---

# Objectif

Implémenter un listener HTTP minimal, dédié aux notifications Hikvision legacy, capable de recevoir les requêtes que les versions récentes d’aiohttp rejettent avant même d’atteindre `EventNotificationsView`.

Le problème principal à résoudre est :

```text
HTTP/1.1 request without Host header
→ aiohttp rejects request
→ hikvision_next never receives event
```

Le nouveau listener doit contourner uniquement cette incompatibilité Hikvision.

Il ne doit PAS affaiblir la sécurité du serveur HTTP Home Assistant.

---

# Résultat cible

Architecture attendue :

```text
                 Hikvision device
                        |
                        |
           +------------+------------+
           |                         |
           v                         v
 HA aiohttp /api/hikvision    Legacy listener
        :8123                  dedicated port
           |                         |
           +------------+------------+
                        |
                        v
           HikvisionEventPayloadParser
                        |
                        v
             HikvisionEventParser
                        |
                        v
            HikvisionEventProcessor
                        |
                        v
                Home Assistant
```

Les deux transports doivent utiliser exactement les mêmes parsers et le même processor.

---

# Contraintes strictes

NE PAS :

* modifier aiohttp ;
* monkey-patcher aiohttp ;
* modifier Home Assistant Core ;
* désactiver la validation HTTP globale ;
* créer un serveur HTTP généraliste ;
* implémenter un proxy ;
* exposer arbitrairement des routes ;
* ajouter de nouvelles features caméra ;
* modifier unique IDs ;
* modifier entity IDs ;
* modifier domain ;
* modifier la logique NVR ;
* ajouter PTZ ;
* ajouter capabilities ;
* ajouter Human/Vehicle entities ;
* ajouter event image entity.

Cette phase concerne uniquement le transport legacy.

---

# 1. Examiner l’implémentation Phase 2

Avant de coder, confirmer que les appels suivants sont utilisables directement :

```python
payload = HikvisionEventPayloadParser().parse(
    body,
    content_type,
)

event = HikvisionEventParser().parse(
    payload.xml,
)

await HikvisionEventProcessor(hass).async_process(
    event,
    source_ip,
)
```

Adapter l’API exacte au code réel.

Ne duplique pas leur logique dans le listener.

---

# 2. Nouveau composant listener

Créer un composant dédié.

Nom suggéré :

```python
HikvisionLegacyHttpListener
```

ou :

```python
HikvisionLegacyEventServer
```

Il peut vivre dans :

```text
custom_components/hikvision_next/legacy_http.py
```

ou :

```text
custom_components/hikvision_next/event_transport.py
```

Évite une arborescence excessive.

---

# 3. Utiliser asyncio.start_server

Le listener doit utiliser :

```python
asyncio.start_server(...)
```

ou une primitive asyncio équivalente qui ne repose pas sur aiohttp.

Exemple conceptuel :

```python
self._server = await asyncio.start_server(
    self._handle_client,
    host=self._host,
    port=self._port,
)
```

Il doit être entièrement non bloquant.

---

# 4. Scope HTTP minimal

Le serveur doit accepter uniquement :

```text
POST /api/hikvision
```

Ne pas implémenter :

```text
GET
PUT
DELETE
PATCH
CONNECT
TRACE
OPTIONS
```

sauf si une nécessité Hikvision réelle et prouvée apparaît.

Pour toute autre méthode :

```text
405 Method Not Allowed
```

Pour tout autre chemin :

```text
404 Not Found
```

ou :

```text
400 Bad Request
```

selon l’implémentation la plus simple et cohérente.

---

# 5. Host header facultatif

Le listener doit explicitement accepter :

```text
POST /api/hikvision HTTP/1.1
Content-Type: application/xml
Content-Length: 1234
```

sans :

```text
Host:
```

C’est la raison principale de ce listener.

NE PAS exiger `Host`.

---

# 6. HTTP versions

Support minimum :

```text
HTTP/1.0
HTTP/1.1
```

Ne pas implémenter HTTP/2.

Ne pas dépendre du header `Connection`.

---

# 7. Parsing des headers

Le parser HTTP doit rester minimal et défensif.

Lire jusqu’à :

```text
\r\n\r\n
```

avec limite stricte.

Exemple :

```python
MAX_HEADER_SIZE = 16 * 1024
```

Ne pas utiliser :

```python
reader.readuntil(...)
```

sans protection de taille.

Le serveur doit interrompre proprement les connexions envoyant des headers excessifs.

---

# 8. Content-Length

Supporter au minimum :

```text
Content-Length
```

Le body doit être lu exactement selon cette valeur.

Valider :

```text
Content-Length >= 0
Content-Length <= MAX_PAYLOAD_SIZE
```

Valeur de départ raisonnable :

```python
MAX_PAYLOAD_SIZE = 16 * 1024 * 1024
```

mais vérifier si les payloads Hikvision JPEG peuvent justifier une autre valeur.

Documenter le choix.

---

# 9. Transfer-Encoding chunked

Ne l’implémente pas automatiquement.

Commence par vérifier les fixtures et comportements Hikvision connus.

Si aucun équipement Hikvision observé n’utilise :

```text
Transfer-Encoding: chunked
```

alors :

```text
reject unsupported transfer encoding
```

avec erreur contrôlée.

Si le code existant ou des fixtures démontrent que Hikvision utilise chunked, implémenter uniquement la partie strictement nécessaire.

Ne construis pas un serveur HTTP complet.

---

# 10. Timeouts

Les connexions doivent avoir des timeouts.

Utiliser par exemple :

```python
asyncio.timeout(...)
```

ou l’équivalent approprié.

Conceptuellement :

```text
HEADER_TIMEOUT = 10 s
BODY_TIMEOUT = 10 s
```

Choisir des valeurs raisonnables.

Le listener ne doit jamais pouvoir rester bloqué indéfiniment sur un client qui ouvre une socket sans envoyer de données.

---

# 11. Source IP

Récupérer :

```python
peername = writer.get_extra_info("peername")
```

et extraire l’adresse IP.

Passer cette valeur au processor :

```python
await processor.async_process(
    event,
    source_ip,
)
```

Ne réimplémente pas la résolution device dans le listener.

---

# 12. Content-Type

Extraire le header de façon case-insensitive.

Par exemple :

```text
Content-Type
content-type
CONTENT-TYPE
```

doivent être équivalents.

Ne parse pas le payload dans le transport.

Passer simplement :

```text
body
content_type
```

à :

```python
HikvisionEventPayloadParser
```

Le parser Phase 2 sait déjà gérer :

```text
application/xml
text/xml
application/x-www-form-urlencoded avec XML
multipart/*
```

Ne duplique pas cette logique.

---

# 13. Multipart et JPEG

Le listener ne doit rien savoir concernant :

```text
XML
JPEG
multipart
```

au-delà du Content-Type brut.

C’est exclusivement la responsabilité de :

```python
HikvisionEventPayloadParser
```

---

# 14. Réponses HTTP

Réponse succès minimale :

```text
HTTP/1.1 200 OK
Content-Length: 0
Connection: close

```

Il est acceptable d’utiliser :

```text
HTTP/1.0 200 OK
```

si cela simplifie et améliore la compatibilité.

Choisir une réponse simple et déterministe.

---

# 15. Politique d’erreur

Définir clairement les réponses.

Par exemple :

```text
malformed request        → 400
unsupported method       → 405
wrong path               → 404
payload too large        → 413
unsupported encoding     → 400 ou 501
parser event failure     → 200 ou 400 selon compatibilité
internal error           → 500
```

IMPORTANT :

Les équipements Hikvision peuvent réessayer agressivement si une notification reçoit autre chose que 200.

Avant de modifier le comportement historique :

évaluer l’impact.

Il peut être préférable que les erreurs de parsing d’un événement Hikvision correctement reçu retournent quand même :

```text
200 OK
```

tout en journalisant l’erreur.

Distinguer :

```text
transport invalid
```

de :

```text
event payload unrecognized
```

Recommandation :

```text
invalid HTTP transport → HTTP error
valid Hikvision POST but event parse fails → 200 + warning
```

afin d’éviter des storms de retry.

Documenter ce choix.

---

# 16. Keep-alive

Ne pas implémenter keep-alive dans cette phase.

Après une requête :

```text
write response
drain
close
```

Chaque notification utilise une connexion indépendante.

C’est acceptable pour le volume attendu.

---

# 17. Lifecycle Home Assistant

Le listener doit être géré proprement par l’intégration.

Il doit être démarré une seule fois.

Il ne doit PAS être créé par chaque ConfigEntry.

Architecture recommandée :

```text
integration-level lifecycle
```

comme `EventNotificationsView` depuis Phase 1.

Le listener doit être stoppé lors de l’arrêt de Home Assistant.

Utiliser les mécanismes HA appropriés.

---

# 18. Plusieurs config entries

Un seul listener doit pouvoir servir :

```text
NVR 1
NVR 2
standalone camera 1
standalone camera 2
```

Le listener ne doit pas appartenir à une seule caméra.

Le processor existant se charge de déterminer la bonne config entry.

---

# 19. Port

Introduire un port dédié.

Proposition par défaut :

```text
8124
```

mais vérifier les conflits possibles.

Créer une constante claire.

Par exemple :

```python
DEFAULT_LEGACY_EVENT_PORT = 8124
```

Ne hardcode pas `8124` dans plusieurs fichiers.

---

# 20. Bind address

Par défaut :

```text
0.0.0.0
```

peut être nécessaire pour recevoir les notifications LAN.

Mais documenter clairement que le serveur est destiné au LAN.

Si Home Assistant expose une adresse spécifique appropriée, évaluer si elle peut être utilisée.

Ne rendre pas le setup fragile en tentant de deviner une interface réseau complexe.

---

# 21. Configuration

Pour cette Phase 3, garder la configuration minimale.

Si le code actuel configure automatiquement Hikvision sur :

```text
HA_IP:8123/api/hikvision
```

ajouter le support du nouveau port.

NE PAS encore construire un Options Flow complexe.

Il est acceptable d’introduire :

```text
legacy listener port
```

comme constante interne dans cette phase.

L’Options Flow peut être amélioré plus tard.

---

# 22. Notification host configuration

Analyser la logique existante qui programme :

```text
alarm server
notification host
```

sur les équipements Hikvision.

Adapter cette logique pour que les équipements nécessitant le mode legacy puissent utiliser :

```text
http://<HA-IP>:8124/api/hikvision
```

Préserver la possibilité d’utiliser :

```text
8123
```

pour le transport aiohttp existant si nécessaire.

---

# 23. Transport mode

Ne construis pas encore un système complexe Auto / alertStream.

Mais préparer une abstraction simple.

Conceptuellement :

```python
class EventTransportMode(Enum):
    HOME_ASSISTANT_HTTP = ...
    LEGACY_HTTP = ...
```

ou une constante équivalente.

N’introduire cette abstraction que si elle simplifie réellement le code.

---

# 24. Compatibilité historique

Le transport aiohttp actuel doit continuer à fonctionner.

Ne le supprime pas.

On doit pouvoir avoir :

```text
8123 → aiohttp standard
8124 → Hikvision legacy listener
```

utilisant :

```text
same parser
same processor
```

---

# 25. Sécurité source

Le listener est volontairement permissif au niveau HTTP `Host`.

Compenser par des protections strictes.

Au minimum :

```text
POST only
path exact
size limits
timeouts
no keep-alive
no generic routing
```

Évaluer également si une allowlist des IP configurées peut être appliquée.

ATTENTION :

Ne bloque pas les setups NVR où les événements peuvent provenir :

```text
NVR IP
camera IP
hostname
proxy channel
```

Si une allowlist stricte risque de casser des setups réels :

ne la rendre pas obligatoire.

On peut plutôt :

```text
process only if HikvisionEventProcessor resolves a known device
```

et logguer les sources inconnues.

---

# 26. Concurrency

Le serveur doit supporter plusieurs notifications simultanées.

Aucun état mutable par requête ne doit être stocké dans le listener.

INTERDIT :

```python
self.current_device
self.current_body
self.current_event
```

Chaque connexion doit conserver son état localement.

---

# 27. Resource limits

Empêcher :

```text
unbounded connections
unbounded body
unbounded headers
```

Il peut être utile d’introduire un semaphore.

Par exemple :

```python
MAX_CONCURRENT_CONNECTIONS = 20
```

ou valeur raisonnable.

Ne complexifie pas excessivement.

Documente si tu implémentes ou non cette limite.

---

# 28. Logging

DEBUG utile :

```text
legacy event connection from x.x.x.x
request method/path
content type
content length
event processed
```

WARNING :

```text
malformed request
payload too large
unsupported method
unknown event
```

Ne jamais logguer :

```text
Authorization
credentials
JPEG body
full binary body
```

---

# 29. Diagnostics internes

Préparer des compteurs simples si cela s’intègre naturellement :

```text
connections_received
events_processed
parse_errors
transport_errors
```

Ne crée pas encore d’entités HA de diagnostics si cela élargit le scope.

Ils pourront être exposés plus tard.

---

# 30. Tests unitaires du parser HTTP legacy

Créer une suite de tests qui n’utilise pas aiohttp.

Test minimum obligatoire :

### Missing Host

```text
POST /api/hikvision HTTP/1.1
Content-Type: application/xml
Content-Length: ...

<XML>
```

sans `Host`.

Résultat :

```text
200
event processed
```

---

### HTTP/1.0

```text
POST /api/hikvision HTTP/1.0
```

Résultat :

```text
200
```

---

### Normal Host

Tester également une requête classique avec :

```text
Host: ...
```

---

### Wrong MIME but XML

```text
Content-Type: application/x-www-form-urlencoded
```

avec body XML.

Résultat :

```text
200
event processed
```

---

### Multipart XML + JPEG

Résultat :

```text
event processed
image retained by payload parser
```

Le listener lui-même ne doit pas inspecter le JPEG.

---

### Wrong method

```text
GET /api/hikvision
```

→ erreur contrôlée.

---

### Wrong path

```text
POST /something
```

→ erreur contrôlée.

---

### Oversized headers

→ connexion rejetée proprement.

---

### Oversized body

→ `413` ou comportement documenté.

---

### Incomplete body

```text
Content-Length: 500
actual body: 100
```

→ timeout/error propre.

---

### Malformed Content-Length

```text
Content-Length: banana
```

→ `400`.

---

# 31. Test end-to-end local

Créer un test lançant réellement :

```python
asyncio.start_server
```

sur un port temporaire :

```text
port 0
```

Récupérer le port assigné.

Envoyer une requête brute avec :

```python
asyncio.open_connection(...)
```

sans `Host`.

Vérifier :

```text
response = 200
processor called once
```

C’est le test le plus important de cette phase.

Il doit prouver que l’erreur aiohttp n’existe plus sur ce transport.

---

# 32. Test concurrent

Si simple à réaliser :

envoyer plusieurs notifications simultanées.

Vérifier :

```text
each event processed once
no shared state
```

---

# 33. Lifecycle tests

Tester :

```text
start listener
stop listener
start listener
```

sans :

```text
Address already in use
duplicate server
leaked socket
```

Tester également que :

```text
multiple ConfigEntry setup
```

ne démarre qu’un seul serveur.

---

# 34. Phase 1 et Phase 2 regression

Tous les tests existants doivent continuer à passer conceptuellement.

Vérifier particulièrement :

```text
NVR channel mapping
HA event payload
unique IDs
entity IDs
setup/unload/reload
```

---

# 35. Gestion du port occupé

Si le port configuré est déjà utilisé :

ne crash pas Home Assistant entier.

Produire une erreur claire.

Idéalement :

```text
listener unavailable
integration continues where possible
```

et log :

```text
Cannot start Hikvision legacy event listener on port 8124: address already in use
```

Ne boucle pas indéfiniment.

---

# 36. Home Assistant stop

S’abonner proprement au stop HA si nécessaire.

À l’arrêt :

```python
server.close()
await server.wait_closed()
```

Les connexions en cours doivent être nettoyées raisonnablement.

---

# 37. Tests environment

Les tests pytest sont toujours bloqués par les dépendances historiques.

Cette phase doit également essayer de rendre le test environment reproductible, mais sans modifier arbitrairement les versions.

Créer éventuellement :

```text
requirements.test.lock.txt
```

ou documenter une combinaison validée uniquement si tu réussis réellement à l’installer.

Ne prétends pas que pytest passe sans exécution réelle.

La validation avec un environnement Python minimal des composants indépendants est acceptable en complément.

---

# 38. Livrable

Créer :

```text
PHASE_3_REPORT.md
```

avec :

## Listener architecture

Décrire :

```text
asyncio socket
→ minimal HTTP parse
→ existing payload parser
→ existing event parser
→ existing processor
```

## HTTP compatibility

Confirmer :

```text
HTTP/1.1 without Host accepted
```

## Port and binding

Documenter defaults.

## Limits

Lister :

```text
header size
payload size
timeouts
concurrency limit
```

## Error policy

Documenter les codes HTTP choisis.

## Security

Expliquer pourquoi le listener n’est pas un serveur HTTP généraliste.

## Lifecycle

Décrire setup/start/stop.

## NVR compatibility

Confirmer qu’elle n’a pas changé.

## aiohttp transport

Confirmer qu’il reste disponible.

## Tests added

Liste complète.

## Tests executed

Commandes exactes et résultats.

## Known limitations

Par exemple :

```text
no chunked transfer encoding
no TLS
LAN-only
```

si applicable.

## Phase 4 readiness

Expliquer ce qui est maintenant prêt pour :

```text
automatic capability detection
```

sans encore l’implémenter.

---

# 39. Git diff

Avant fin :

```text
git status
git diff
git diff --check
```

Inspecter entièrement le diff.

Pas de fichiers temporaires.

Pas de credentials.

Pas de dumps réseau.

---

# 40. Commit

Si approprié :

```text
feat: add legacy Hikvision event listener
```

Ne push rien.

---

# 41. Critères d’acceptation

Phase 3 terminée uniquement si :

* listener dédié basé sur asyncio ;
* aucune dépendance aiohttp dans ce listener ;
* requête HTTP/1.1 sans Host acceptée ;
* parser Phase 2 réutilisé ;
* processor Phase 2 réutilisé ;
* aucun parsing XML dupliqué ;
* aucun parsing multipart dupliqué ;
* limites headers/body ;
* timeout ;
* lifecycle propre ;
* plusieurs config entries supportées ;
* aiohttp transport existant préservé ;
* aucune modification unique/entity IDs ;
* tests raw socket ajoutés ;
* test Missing Host ajouté ;
* `PHASE_3_REPORT.md` créé.

---

# 42. Arrêt obligatoire

À la fin afficher :

```text
Phase 3 complete.

Legacy Hikvision HTTP listener implemented.
HTTP/1.1 notifications without Host can now bypass aiohttp safely.

See PHASE_3_REPORT.md
```

Puis arrête-toi.

N’entame pas la Phase 4.

N’ajoute pas encore capability discovery.
