# Phase 1 — Baseline Home Assistant 2026 Compatibility & Regression Safety

Tu travailles dans le dépôt `hikvision_next_level`.

Avant toute modification, lis intégralement :

* `PROJECT_REFERENCE.md`
* `AUDIT_PHASE_0.md`

Le rapport de Phase 0 est basé sur le code réel du fork `itsjustdeepred/hikvision_next` et constitue désormais la référence technique pour cette phase.

---

# Objectif

Établir une base `hikvision_next` propre, testable et compatible avec les versions actuelles de Home Assistant avant de refactorer le moteur d’événements.

Cette phase doit :

1. corriger les incompatibilités Home Assistant évidentes identifiées dans l’audit ;
2. préserver la compatibilité avec les installations existantes ;
3. sécuriser le lifecycle setup / unload / reload ;
4. consolider les unique IDs et entity IDs ;
5. créer les premiers tests de non-régression indispensables ;
6. préparer le terrain pour la future refonte du système d’événements.

Cette phase ne doit PAS encore :

* implémenter le listener HTTP raw compatible Hikvision ;
* modifier aiohttp ;
* implémenter `asyncio.start_server`;
* implémenter alertStream ;
* ajouter PTZ ;
* ajouter lumière IR / ColorVu ;
* ajouter Human / Vehicle distincts ;
* ajouter snapshots HD ;
* ajouter de nouvelles features utilisateur.

---

# 1. Commencer par relire les conclusions de l’audit

Avant de modifier quoi que ce soit, vérifie dans `AUDIT_PHASE_0.md` :

* quels fichiers sont concernés par la compatibilité Home Assistant ;
* quels correctifs du fork `itsjustdeepred` sont déjà présents ;
* comment les unique IDs sont actuellement générés ;
* comment les entity IDs ont déjà été corrigés ;
* comment `hass.data` est utilisé ;
* comment setup/unload fonctionne ;
* quelles APIs Home Assistant sont potentiellement obsolètes ;
* quelles parties du listener événement ne doivent PAS être modifiées dans cette phase.

Ne réimplémente pas un correctif déjà présent.

---

# 2. Créer un état Git propre

Avant les modifications :

```text
git status
```

Vérifie qu’aucune modification utilisateur inattendue n’est présente.

Ne supprime ni n’écrase aucune modification existante.

Créer une branche de travail si approprié, par exemple :

```text
phase-1-ha-compat
```

Ne modifie pas le remote upstream sans nécessité.

---

# 3. Home Assistant compatibility audit ciblé

Sur la base de l’audit Phase 0, corrige uniquement les problèmes réels.

Vérifier particulièrement :

## ConfigEntry lifecycle

* `async_setup_entry`
* `async_unload_entry`
* reload éventuel
* update listeners
* cleanup listeners
* cleanup tasks
* cleanup event handlers

Chaque ressource enregistrée pendant setup doit être correctement supprimée lors de unload.

Un cycle :

```text
setup
→ unload
→ setup
```

ne doit pas créer de duplication.

---

# 4. Runtime data

Si le projet utilise actuellement :

```python
hass.data[DOMAIN][entry.entry_id]
```

ne transforme pas toute l’intégration brutalement uniquement pour moderniser le style.

Évalue d’abord le risque.

Si une migration progressive vers :

```python
entry.runtime_data
```

peut être faite proprement sans casser les plateformes existantes, implémente une structure typée.

Conceptuellement :

```python
@dataclass
class HikvisionRuntimeData:
    ...
```

Mais ne crée pas une abstraction inutile.

Priorité :

```text
compatibilité > lisibilité > modernisation esthétique
```

Si `hass.data` fonctionne correctement et qu’une migration risque de toucher trop de fichiers avant la Phase 2, documente la migration comme travail futur plutôt que de forcer le changement maintenant.

---

# 5. Entity IDs

Le fork `itsjustdeepred` contient déjà un correctif concernant les entity IDs.

Analyse précisément ce correctif avant toute modification.

Objectif :

Home Assistant doit pouvoir générer des entity IDs valides même lorsque les identifiants Hikvision contiennent :

```text
/
-
espaces
majuscules
caractères inhabituels
```

Ne réintroduis pas de génération manuelle fragile.

Ne force pas `entity_id` lorsque Home Assistant peut le gérer proprement.

---

# 6. Unique IDs

Les `unique_id` sont beaucoup plus sensibles que les entity IDs.

Ne change aucun format de `unique_id` sans justification absolue.

Pour chaque plateforme existante :

```text
camera
image
binary_sensor
sensor
switch
button
```

ou autres plateformes réellement présentes :

vérifie que les unique IDs sont :

* déterministes ;
* stables après restart ;
* uniques entre plusieurs channels NVR ;
* uniques entre plusieurs NVR ;
* uniques entre standalone camera et NVR channel ;
* indépendants du nom utilisateur lorsque possible.

Ne transforme pas les unique IDs simplement pour les rendre plus beaux.

Si un format historique est imparfait mais stable :

```text
KEEP IT
```

sauf s’il provoque réellement des collisions.

Si une migration est indispensable, utilise les mécanismes Home Assistant appropriés et documente précisément le changement.

---

# 7. Device Registry

Vérifie la création des devices Home Assistant.

Préserver impérativement la structure :

```text
NVR
 |
 +-- Channel / camera 1
 |
 +-- Channel / camera 2
 |
 +-- Channel / camera 3
```

si c’est la structure actuelle.

Vérifie :

* identifiers ;
* manufacturer ;
* model ;
* firmware version ;
* connections éventuelles ;
* `via_device`.

Ne casse pas les relations existantes.

---

# 8. Async correctness

Cherche les appels potentiellement bloquants effectués dans l’event loop Home Assistant.

Notamment :

```text
requests
urllib sync
time.sleep
filesystem sync lourd
socket sync
XML traitement extrêmement lourd
```

Ne fais pas une optimisation prématurée.

Corrige uniquement les appels clairement problématiques.

Pour les opérations réseau Hikvision existantes :

* vérifier les timeouts ;
* vérifier les exceptions ;
* vérifier qu’une caméra offline ne bloque pas tout le setup.

---

# 9. Error isolation

Une erreur sur un channel NVR ne doit pas détruire tous les autres channels si l’architecture actuelle permet une isolation raisonnable.

Vérifie les chemins :

```text
NVR
 → enumerate channels
 → initialize channel
 → create entities
```

et assure-toi qu’un channel invalide ou offline produit :

```text
warning/error ciblé
```

plutôt qu’un crash global lorsque cela peut être évité proprement.

Ne change pas profondément l’architecture NVR dans cette phase.

---

# 10. Logging

Nettoie uniquement les problèmes évidents.

Ne log jamais :

```text
password
Authorization
Digest credentials
tokens
```

Évite les logs énormes contenant :

```text
JPEG
payload binary
XML gigantesque
```

Préserver des logs DEBUG utiles.

---

# 11. Manifest

Vérifie :

```text
manifest.json
```

pour les exigences Home Assistant actuelles.

Contrôler notamment :

* domain ;
* name ;
* version ;
* documentation ;
* issue_tracker ;
* codeowners si applicable ;
* requirements ;
* config_flow ;
* iot_class.

Le domain reste impérativement :

```text
hikvision_next
```

Ne le renomme pas en :

```text
hikvision_next_level
```

Le nom du repository peut être `hikvision_next_level`, mais pas le domain HA.

---

# 12. Tests de non-régression Phase 1

L’audit indique que les dépendances n’ont pas pu être installées à cause d’un problème réseau.

Commence par inspecter le système de tests existant.

Si l’environnement permet maintenant l’installation des dépendances, installe uniquement les dépendances nécessaires.

Ne modifie pas des versions de dépendances au hasard pour forcer les tests à passer.

Si le réseau bloque toujours :

1. continue les modifications pouvant être validées statiquement ;
2. exécute `compileall` ou équivalent ;
3. exécute les outils disponibles localement ;
4. documente précisément les tests non exécutés.

Ne prétends jamais qu’un test est passé s’il n’a pas été exécuté.

---

# 13. Tests à créer en priorité

Créer des tests ciblés sur la compatibilité actuelle.

## Config setup

Tester :

```text
config entry setup succeeds
```

avec un appareil simulé/minimal.

## Config unload

Tester :

```text
setup
unload
```

sans exception.

## Reload

Si l’architecture le permet raisonnablement :

```text
setup
unload
setup
```

et vérifier qu’il n’existe pas de listeners dupliqués.

## Unique IDs

Ajouter des cas pour :

```text
standalone camera
NVR
NVR channel
serial contenant caractères inhabituels
```

Vérifier la stabilité des unique IDs.

## Entity naming

Tester les cas qui avaient causé les bugs connus du dépôt upstream.

Ne teste pas le fonctionnement interne de Home Assistant inutilement.

Teste le comportement attendu de l’intégration.

---

# 14. Ajouter les fixtures événements maintenant ?

Seulement partiellement.

Préparer le dossier de fixtures si cela s’intègre naturellement aux tests existants.

Il est acceptable de créer dès maintenant :

```text
tests/fixtures/events/
```

avec quelques exemples minimaux.

Mais ne commence pas encore à réécrire le parser événement.

Les tests spécifiques suivants appartiennent principalement aux Phases 2 et 3 :

```text
missing Host
wrong MIME type
multipart XML + JPEG
```

Ils peuvent être ajoutés comme fixtures documentaires maintenant, mais ne doivent pas provoquer un refactor prématuré.

---

# 15. Ne pas corriger le problème `Missing Host` dans cette phase

C’est important.

L’audit a confirmé que :

```text
Missing 'Host' header in request
```

est rejeté par aiohttp avant que le handler actuel de `hikvision_next` soit appelé.

Ne cherche donc pas à résoudre ce problème avec :

```python
request.headers(...)
```

ou en modifiant simplement :

```python
parse_event_request()
```

Cela ne peut pas résoudre le problème.

Ne monkey-patch pas aiohttp.

La solution dédiée sera développée en Phase 3.

---

# 16. MIME Hikvision

Même principe.

L’audit a confirmé que certains équipements Hikvision utilisent incorrectement :

```text
application/x-www-form-urlencoded
```

pour transporter du XML.

Ne refactore pas encore complètement le parser dans cette Phase 1.

Il est acceptable de faire uniquement un correctif minimal et évident si celui-ci est :

* isolé ;
* rétrocompatible ;
* couvert par un test ;
* sans impact sur l’architecture événement.

Mais si cela nécessite de toucher profondément le système d’événements :

```text
DEFER TO PHASE 2
```

Documenter le point.

---

# 17. Préparer la future séparation EventManager

Sans l’implémenter encore, identifier précisément les limites actuelles entre :

```text
HTTP transport
HTTP request parsing
multipart parsing
XML parsing
device/channel lookup
event state update
HA event firing
```

Si de petits renommages ou annotations de types facilitent clairement la Phase 2 sans changer le comportement, ils sont acceptables.

Pas de gros refactor.

---

# 18. Qualité du code

Utiliser les conventions déjà présentes dans le projet.

Ajouter des annotations de type lorsque pertinentes.

Ne transforme pas tout le repository simplement pour satisfaire un style différent.

Pas de :

```text
mass formatting
mass renaming
mass import sorting
```

sans raison.

Cela rendrait le diff inutilement difficile à examiner.

---

# 19. Livrables

À la fin de cette phase :

Créer :

```text
PHASE_1_REPORT.md
```

contenant :

## Changes made

Liste des corrections réellement effectuées.

## Compatibility fixes

Problèmes Home Assistant corrigés.

## Unique ID impact

Indiquer explicitement :

```text
changed / unchanged
```

et pourquoi.

## Entity ID impact

Expliquer le comportement après correction.

## ConfigEntry lifecycle

Décrire setup/unload/reload.

## NVR compatibility

Indiquer ce qui a été vérifié.

## Tests added

Lister les tests.

## Tests executed

Lister exactement les commandes exécutées et leur résultat.

Exemple :

```text
python -m compileall ... : PASS
pytest ... : NOT RUN - dependency installation blocked by network
```

## Remaining known issues

Inclure explicitement :

```text
Legacy Hikvision HTTP requests without Host remain unsupported.
This is intentionally deferred to Phase 3.
```

si c’est toujours le cas.

## Phase 2 readiness

Lister les fichiers qui devront être touchés pour séparer :

```text
transport
parser
event processing
```

---

# 20. Git diff review

Avant de terminer :

```text
git diff
git status
```

Inspecter le diff complet.

Supprimer :

* fichiers temporaires ;
* caches ;
* dumps ;
* credentials ;
* modifications accidentelles.

Le diff doit être limité à la Phase 1.

---

# 21. Commit

Si l’environnement Git est configuré et qu’aucune instruction locale ne l’interdit, créer un commit logique du type :

```text
fix: establish Home Assistant compatibility baseline
```

Ne pousser aucun commit vers un remote sans instruction explicite.

---

# 22. Critères d’acceptation

La Phase 1 est terminée seulement si :

* Python compile ;
* aucune nouvelle feature n’a été ajoutée ;
* domain toujours `hikvision_next`;
* comportement NVR existant préservé ;
* unique IDs existants préservés sauf nécessité documentée ;
* entity IDs invalides traités proprement ;
* setup/unload cohérent ;
* tests de base ajoutés ;
* résultats des tests documentés honnêtement ;
* aucune modification aiohttp globale ;
* aucun listener raw ajouté ;
* `PHASE_1_REPORT.md` créé.

---

# 23. Arrêt obligatoire

Après avoir terminé :

affiche un résumé concis avec :

```text
Phase 1 complete.

Compatibility baseline established.
See PHASE_1_REPORT.md

Known deferred issue:
Hikvision HTTP notifications without Host header remain for Phase 3.
```

Puis arrête-toi.

N’entame pas la Phase 2.

N’implémente pas le nouveau moteur d’événements.

N’implémente pas le listener `asyncio.start_server`.

Attends une instruction explicite pour continuer.
