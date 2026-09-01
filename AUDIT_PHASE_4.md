# Phase 4 — Automatic Capability Discovery

Tu travailles dans le dépôt `hikvision_next_level`.

Avant toute modification, lis intégralement :

* `PROJECT_REFERENCE.md`
* `AUDIT_PHASE_0.md`
* `PHASE_1_REPORT.md`
* `PHASE_2_REPORT.md`
* `PHASE_3_REPORT.md`

Les Phases 1 à 3 ont établi :

```text
HA compatibility baseline
→ event architecture separation
→ legacy HTTP listener
```

Ne remets pas en cause ces fondations sans bug concret.

---

# Objectif

Introduire une détection centralisée et fiable des capacités Hikvision afin que l’intégration puisse déterminer automatiquement ce que chaque caméra ou channel NVR supporte.

Le résultat doit permettre aux phases suivantes de créer uniquement les entités réellement pertinentes.

Exemple :

```text
Camera A
├─ PTZ                  yes
├─ presets              yes
├─ IR                   yes
├─ white light          yes
├─ Smart Hybrid Light   yes
├─ Day/Night            yes
├─ siren                no
└─ image controls       partial

Camera B
├─ PTZ                  no
├─ IR                   yes
├─ white light          no
├─ Day/Night            yes
└─ siren                no
```

L’intégration ne doit plus dépendre principalement de listes de modèles.

---

# Contraintes principales

Dans cette phase :

NE PAS encore implémenter les contrôles utilisateurs pour :

* PTZ ;
* presets ;
* IR ;
* white light ;
* Smart Hybrid Light ;
* Day/Night ;
* image settings ;
* audio/siren ;
* detection sensitivity ;
* Soft Alarm Inputs.

Cette phase ne fait que découvrir et représenter les capabilities.

Ne crée pas encore toutes les nouvelles entités.

Ne change pas :

* domain ;
* unique IDs ;
* entity IDs ;
* NVR mapping ;
* event transport ;
* legacy listener ;
* existing HA event payload.

---

# 1. Auditer les endpoints de capability existants

Avant de coder, rechercher dans le dépôt tous les usages de :

```text
/capabilities
```

et les endpoints ISAPI liés à :

```text
System
Streaming
Image
PTZCtrl
Event
Audio
IO
```

Identifier :

* endpoints déjà appelés ;
* réponses déjà parsées ;
* éventuels champs `opt=`;
* endpoints qui retournent 404/405/403 selon modèle ;
* logique existante basée sur modèles.

Documenter brièvement l’état avant modification.

---

# 2. Ne pas dépendre d’un seul endpoint global

Ne suppose pas que :

```text
/ISAPI/System/capabilities
```

décrit correctement toutes les fonctionnalités.

Les firmwares Hikvision sont hétérogènes.

La détection doit pouvoir combiner :

```text
capability endpoints
+
feature-specific capability endpoints
+
safe endpoint probing
```

Exemple conceptuel :

```text
System capabilities
      |
      +-- Streaming capabilities
      |
      +-- Image capabilities
      |
      +-- PTZ capabilities
      |
      +-- Event capabilities
      |
      +-- Audio capabilities
```

---

# 3. Créer un modèle central de capabilities

Créer une représentation typée.

Une structure possible :

```python
@dataclass(slots=True)
class HikvisionCapabilities:
    # Streams
    main_stream: bool = True
    sub_stream: bool = False
    third_stream: bool = False

    # PTZ
    ptz: bool = False
    ptz_presets: bool = False

    # Lighting
    ir_light: bool = False
    white_light: bool = False
    smart_hybrid_light: bool = False
    light_brightness: bool = False

    # Detection
    motion_detection: bool = False
    line_crossing: bool = False
    intrusion_detection: bool = False
    human_filter: bool = False
    vehicle_filter: bool = False

    # Day/night
    day_night: bool = False
    day_night_sensitivity: bool = False
    day_night_delay: bool = False

    # Image
    brightness: bool = False
    contrast: bool = False
    saturation: bool = False
    sharpness: bool = False
    wdr: bool = False
    blc: bool = False
    hlc: bool = False
    gain: bool = False
    shutter: bool = False
    noise_reduction: bool = False
    defog: bool = False

    # Audio
    microphone: bool = False
    speaker: bool = False
    siren: bool = False

    # NVR
    alarm_inputs: bool = False
    soft_alarm_inputs: bool = False
```

Cette liste est indicative.

Adapte-la aux vraies données disponibles.

Ne crée pas de capability purement spéculative sans endpoint ou utilisation prévue.

---

# 4. Préférer des sous-modèles si nécessaire

Si le modèle devient trop plat, il est acceptable d’utiliser :

```python
@dataclass(slots=True)
class PTZCapabilities:
    supported: bool
    presets: bool


@dataclass(slots=True)
class LightingCapabilities:
    ir: bool
    white: bool
    smart_hybrid: bool
```

puis :

```python
@dataclass(slots=True)
class HikvisionCapabilities:
    ptz: PTZCapabilities
    lighting: LightingCapabilities
    ...
```

Choisir la structure la plus claire.

Ne pas créer une architecture abstraite inutile.

---

# 5. Capability discovery service

Créer un composant central, par exemple :

```python
class HikvisionCapabilityDiscovery:
```

avec une API du type :

```python
capabilities = await discovery.async_discover(device)
```

ou équivalent adapté au client actuel.

Le reste du code ne doit pas appeler directement dix endpoints différents pour savoir si PTZ existe.

---

# 6. Réutiliser le client ISAPI

La discovery doit utiliser le client ISAPI existant.

Ne duplique pas :

* authentification ;
* timeout ;
* requêtes HTTP ;
* XML parsing générique.

Si le client ISAPI actuel manque d’une méthode générique propre pour :

```text
GET endpoint
→ XML
```

il est acceptable de l’améliorer légèrement.

Mais ne transforme pas toute la couche ISAPI.

---

# 7. Standalone camera vs NVR channel

La discovery doit explicitement gérer les deux cas.

## Standalone camera

Les endpoints peuvent être directement :

```text
/ISAPI/Image/channels/1/...
/ISAPI/PTZCtrl/channels/1/...
```

## NVR channel

Le numbering peut être différent :

```text
101
102
201
...
```

ou dépendre du channel proxy.

Ne hardcode pas les channels dans la discovery si le code actuel sait déjà les résoudre.

Réutiliser le mapping existant.

---

# 8. Capability probing

Lorsqu’un endpoint capability fiable n’existe pas, un probe contrôlé est acceptable.

Exemple conceptuel :

```text
GET PTZ capability endpoint
→ 200 = supported
→ 404 = unsupported
→ 405 = possibly unsupported
→ 403 = endpoint exists but permission problem
```

ATTENTION :

```text
403 != unsupported
```

Un manque de permission doit être distingué d’une feature absente.

Créer si utile un état interne :

```text
supported
unsupported
unknown
```

plutôt qu’un simple bool partout.

---

# 9. Support tri-state si nécessaire

Pour certains endpoints, il peut être utile d’avoir :

```python
class CapabilityState(Enum):
    SUPPORTED = ...
    UNSUPPORTED = ...
    UNKNOWN = ...
```

Cela permet de distinguer :

```text
feature absent
```

de :

```text
request impossible à vérifier
```

Ne l’utilise que si cela simplifie réellement le comportement.

---

# 10. Parsing `opt=`

Hikvision utilise souvent des attributs du type :

```xml
mode opt="auto,day,night">
```

ou :

```xml
enabled opt="true,false">
```

Extraire et conserver les valeurs permises lorsque cela sera nécessaire aux futures entités.

Par exemple :

```python
@dataclass
class SelectCapability:
    supported: bool
    options: tuple[str, ...]
```

Cela sera très utile plus tard pour :

```text
Day / Night
Light Mode
WDR modes
```

---

# 11. Ranges numériques

Même principe pour les capacités numériques.

Si Hikvision expose :

```text
min
max
step
```

ne conserve pas uniquement :

```text
supported=True
```

Créer une structure conceptuelle :

```python
@dataclass(slots=True)
class NumericCapability:
    supported: bool
    minimum: float | None
    maximum: float | None
    step: float | None
```

Très important pour les futures entités :

```text
brightness
white light brightness
motion sensitivity
gain
etc.
```

---

# 12. Capability cache

La discovery ne doit pas interroger tous les endpoints à chaque update du coordinator.

Les capabilities sont relativement statiques.

Effectuer normalement :

```text
config entry setup
→ capability discovery
→ cache
```

Puis réutiliser le résultat.

---

# 13. Rediscovery

Préparer une méthode :

```python
async_rediscover_capabilities()
```

mais ne crée pas encore obligatoirement le bouton HA.

L’objectif est de pouvoir rescanner après :

```text
firmware update
camera replacement
configuration change
```

Ne lance pas un scan complet toutes les minutes.

---

# 14. Intégration runtime

Stocker les capabilities dans le runtime existant d’une manière cohérente.

La Phase 1 a confirmé que :

```text
ConfigEntry[HikvisionDevice]
entry.runtime_data
```

est déjà utilisée proprement.

Ne crée pas un wrapper massif uniquement pour stocker un objet supplémentaire.

Si `HikvisionDevice` est la bonne place :

```python
device.capabilities
```

est acceptable.

Sinon utiliser une structure runtime adaptée.

---

# 15. Capabilities par camera/channel

Attention :

un NVR peut avoir :

```text
channel 1 = fixed camera
channel 2 = ColorVu
channel 3 = PTZ
channel 4 = /SL
```

Les capabilities doivent donc être au niveau du device/channel approprié.

Ne stocke pas simplement :

```python
nvr.capabilities.ptz = True
```

si seul le channel 3 est PTZ.

---

# 16. Capabilities NVR globales

Certaines capabilities appartiennent en revanche au NVR lui-même :

```text
storage
alarm outputs
soft alarm inputs
CPU/RAM
```

Préserver cette distinction.

Conceptuellement :

```text
NVR capabilities
      |
      +-- channel 1 capabilities
      +-- channel 2 capabilities
      +-- channel 3 capabilities
```

---

# 17. Ne pas casser setup si discovery échoue

Une erreur de capability discovery ne doit pas empêcher la caméra de fonctionner si le reste de l’intégration peut fonctionner.

Exemple :

```text
PTZ capability endpoint timeout
```

ne doit pas empêcher :

```text
camera
snapshot
events
```

de se charger.

Utiliser des fallbacks raisonnables.

---

# 18. Conserver les features existantes

Attention aux fonctionnalités déjà exposées par l’intégration.

Si une feature existe historiquement mais que la nouvelle discovery retourne `unknown`, ne la supprime pas automatiquement si cela risque de casser les utilisateurs.

La Phase 4 doit être conservative.

Pour les entités existantes :

```text
existing behavior wins
```

tant qu’une migration explicite n’est pas faite.

La capability registry servira surtout aux nouvelles features.

---

# 19. Logging discovery

Ajouter du DEBUG utile :

```text
Discovering capabilities for <device>
PTZ: supported
White light: unsupported
Smart Hybrid Light: supported
Day/night modes: auto,day,night
```

Ne pas spammer les logs en INFO.

Un résumé DEBUG par device est suffisant.

---

# 20. Performance

Le scan initial doit rester raisonnable.

Éviter :

```text
50 sequential HTTP requests
```

si certaines peuvent être évitées ou regroupées.

Mais ne parallélise pas tout sans limite.

Une petite concurrence contrôlée est acceptable si elle est utile.

Priorité :

```text
reliability > startup speed
```

---

# 21. Timeout individuel

Chaque probe doit avoir un timeout raisonnable via le client existant.

Une feature absente ou inaccessible ne doit pas bloquer setup pendant longtemps.

---

# 22. Tests unitaires capability

Créer des fixtures pour au moins :

## Fixed camera

```text
no PTZ
IR supported
Day/Night supported
```

## ColorVu / hybrid light camera

```text
white light
IR
Smart Hybrid Light
brightness control
```

## PTZ camera

```text
PTZ
presets
zoom
```

## `/SL` camera

```text
speaker
siren
possibly white light
```

## NVR with mixed channels

```text
channel 1 fixed
channel 2 PTZ
channel 3 ColorVu
```

---

# 23. Test permissions

Ajouter un test où :

```text
PTZ endpoint → 403
```

Le résultat ne doit pas être :

```text
PTZ unsupported
```

si le code ne peut pas le conclure.

Préserver `unknown` ou fallback approprié.

---

# 24. Test endpoint absent

Cas :

```text
GET feature endpoint → 404
```

doit pouvoir produire :

```text
unsupported
```

si cela est cohérent avec l’API Hikvision concernée.

---

# 25. Test malformed capability XML

Un XML capability invalide doit produire :

```text
warning/debug
capability unknown
```

pas un crash global.

---

# 26. Test numeric ranges

Ajouter au moins un fixture avec :

```text
min=0
max=100
step=1
```

et vérifier que la structure numérique est correctement construite.

---

# 27. Test select options

Ajouter au moins un fixture avec :

```text
opt="auto,day,night"
```

et vérifier :

```text
("auto", "day", "night")
```

---

# 28. Ne pas encore créer les nouvelles entités

La Phase 4 doit terminer avec des capabilities inspectables dans le code/tests.

Ne crée pas encore :

```text
select.<camera>_day_night
number.<camera>_brightness
select.<camera>_light_mode
```

Ces entités arriveront dans les phases suivantes.

---

# 29. Optionnel : diagnostic temporaire

Il est acceptable d’ajouter en DEBUG un dump synthétique du registry.

Ne crée pas un sensor contenant tout le JSON des capabilities.

---

# 30. Documentation interne

Créer si utile :

```text
CAPABILITIES.md
```

avec un tableau :

```text
Feature
ISAPI endpoint
Parsing method
Standalone
NVR channel
Confidence
```

Ce fichier serait très utile pour les phases suivantes.

Il peut aussi être intégré dans `PHASE_4_REPORT.md`.

---

# 31. Tester sur la vraie instance Home Assistant

Le workflow SFTP est maintenant disponible.

Après validation statique :

déployer le composant sur l’instance HA de développement.

Important :

ne modifie pas directement les fichiers sur HA sans que les changements existent également dans le repository Git local.

Le repository local reste la source de vérité.

---

# 32. Validation réelle

Sur au moins un équipement réel Hikvision disponible :

collecter les capabilities découvertes.

Logguer temporairement en DEBUG si nécessaire.

Vérifier que les résultats correspondent aux fonctions visibles dans l’interface Hikvision.

Ne modifier aucune configuration caméra pendant cette validation.

---

# 33. Prévoir plusieurs appareils

Si plusieurs modèles Hikvision sont disponibles, tester idéalement :

```text
une caméra fixe
une caméra avec fonctions avancées
un NVR
```

Mais ne bloque pas la phase si seulement un ou deux appareils sont disponibles.

Documenter les appareils testés.

---

# 34. Test environment pytest

Le problème de dépendances pytest reste ouvert.

Ne mélange pas ce problème avec la capability discovery.

Si un environnement de test exécutable peut être obtenu proprement, fais-le.

Sinon :

```text
compileall
git diff --check
runtime testing HA dev
```

doivent être documentés précisément.

---

# 35. Livrable

Créer :

```text
PHASE_4_REPORT.md
```

avec les sections :

## Architecture

Décrire le registry/discovery.

## Capability model

Lister les structures créées.

## Endpoints used

Tableau :

```text
Feature | Endpoint | Interpretation
```

## Standalone vs NVR

Décrire la gestion.

## Unknown vs unsupported

Expliquer la stratégie.

## Numeric ranges

Expliquer comment min/max/step sont conservés.

## Select options

Expliquer `opt=`.

## Cache strategy

Décrire quand le scan est effectué.

## Failure handling

Décrire comment les erreurs sont isolées.

## Tests added

Liste.

## Tests executed

Résultats exacts.

## Real hardware validation

Lister :

```text
model
firmware
detected capabilities
unexpected results
```

sans credentials.

## Known limitations

Lister les capabilities encore incertaines.

## Phase 5 readiness

Expliquer précisément comment la prochaine phase pourra créer :

```text
Human / Vehicle events
```

et/ou utiliser les capabilities sans toucher à l’architecture.

---

# 36. Git review

Avant fin :

```text
git status
git diff
git diff --check
```

Vérifier qu’aucune nouvelle feature utilisateur n’a été ajoutée.

---

# 37. Commit

Si approprié :

```text
feat: add Hikvision capability discovery
```

Ne push rien.

---

# 38. Critères d’acceptation

Phase 4 terminée uniquement si :

* capability model central existe ;
* discovery centralisée existe ;
* standalone et NVR channels pris en charge ;
* pas de dépendance principale à une liste de modèles ;
* options `opt=` conservées ;
* ranges numériques conservés lorsque disponibles ;
* distinction unsupported / unknown faite là où nécessaire ;
* discovery ne casse pas setup en cas d’erreur partielle ;
* cache présent ;
* aucune nouvelle entité fonctionnelle ajoutée ;
* unique IDs inchangés ;
* entity IDs inchangés ;
* tests ajoutés ;
* `PHASE_4_REPORT.md` créé.

---

# 39. Arrêt obligatoire

À la fin afficher :

```text
Phase 4 complete.

Automatic Hikvision capability discovery implemented.
No new user-facing controls were added.

See PHASE_4_REPORT.md
```

Puis arrête-toi.

N’entame pas la Phase 5.
