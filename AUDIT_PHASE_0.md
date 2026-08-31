# Audit Phase 0 — Hikvision Next

Date : 31 août 2026
Base auditée : `itsjustdeepred/hikvision_next`, commit `8878039473a31ae23f9f39c08eaece1c93dc0db1` (tag `v1.2.0`)

## A. Executive summary

Le workspace contient désormais le fork ciblé, récupéré depuis son remote public. C'est un fork direct de `maciej-or/hikvision_next` : le merge-base et le HEAD amont vérifié sont tous deux `f6dac0dabb26281cf6e287181621ffbead573ce9` (release v1.1.1 amont). Le fork ajoute trois commits : `1f25fa6` (entity IDs/snapshot image), `ed13224` (métadonnées et documentation du fork) et `8878039` (version 1.2.0).

Le correctif du fork est réel et ciblé : il slugifie les *entity IDs* des capteurs de stockage/Notification Host, sans modifier leurs unique IDs, et enregistre les snapshots sous le domaine `image`. Il ne corrige pas les entity IDs forcés dans `camera`, `binary_sensor` et `switch`.

L'intégration dispose d'un client ISAPI async centralisé (`httpx`), d'un modèle NVR/canaux robuste sur plusieurs aspects, de coordinators de polling et d'un endpoint Home Assistant `/api/hikvision`. Le risque principal est le flux d'événements : il dépend directement de l'analyseur HTTP aiohttp de HA, accepte uniquement quelques Content-Type exacts, traite à tort les autres corps comme multipart et ignore les JPEG. Une requête HTTP/1.1 sans `Host` est rejetée par aiohttp avant l'appel du code de l'intégration.

Aucune phase fonctionnelle n'a été commencée et aucun fichier de production n'a été modifié. La compilation de tous les fichiers Python réussit. La suite pytest n'a pas pu être exécutée : l'installation de ses dépendances a été interrompue après plusieurs minutes sans progrès réseau ; `.venv/` est conservé pour reprise.

## B. Current architecture

| Élément | Implémentation actuelle |
| --- | --- |
| Entrée / domaine | `custom_components/hikvision_next/__init__.py`; domaine inchangé `hikvision_next`; plateformes : binary sensor, camera, sensor, switch, image. |
| Config flow | `config_flow.py`; host, SSL, identifiants, hôte d'alarme, port RTSP forcé; reconfiguration et reauth, mais pas d'Options Flow. |
| Runtime data | Alias `ConfigEntry[HikvisionDevice]`; `entry.runtime_data = HikvisionDevice` dans `__init__.py`. |
| Client / modèle | `hikvision_device.py` spécialise `isapi/ISAPIClient`; modèles dataclass dans `isapi/models.py`. |
| Coordinators | `coordinator.py`: événements/sorties/stockage toutes les 120 s; mode vacances/Notification Host toutes les 60 min. |
| NVR/canaux | `isapi/isapi.py`: discovery des canaux IP proxifiés et analogiques, streams par canal, device registry parent/enfant. |
| Événements push | `notifications.py`: `HomeAssistantView` à `/api/hikvision`, XML avec `xmltodict`, multipart via `requests_toolbelt`. |
| Entités | `camera.py`, `image.py`, `binary_sensor.py`, `switch.py`, `sensor.py`; aucun `button`, `select`, `number`, `siren` ou autre plateforme. |
| Services | `services.py`: reboot et requête ISAPI personnalisée. |
| Diagnostics | `diagnostics.py`: collecte et anonymise des réponses ISAPI. |
| Traductions | `strings.json` et traductions en, fr, it, pl, pt, pt-BR, ru. |

Le setup crée le device parent dans le registry, découvre matériel/capabilities/canaux, initialise les coordinators, forwarde les plateformes puis enregistre la vue HTTP une fois pour la première config entry active.

## C. Event flow

Flux réel :

```text
Caméra / NVR
  → configuration ISAPI PUT Event/notification/httpHosts (optionnelle)
  → POST /api/hikvision
  → aiohttp / HomeAssistantView EventNotificationsView.post()
  → request.read() et parse_event_request()
  → ISAPIClient.parse_event_notification() (xmltodict)
  → sélection de ConfigEntry par MAC, sinon IP source
  → normalisation du channel NVR (>32 → caméra IP / input port)
  → lookup de l'entité binary_sensor dans le registry
  → hass.states.async_set(..., on, attributs existants)
  → hass.bus.fire("hikvision_next_event", données enrichies)
```

Fichiers : route et traitement HTTP dans `notifications.py`; constante `/api/hikvision` dans `const.py`; configuration de l'URL dans `isapi/isapi.py:set_alarm_server`; modèles d'alerte dans `isapi/models.py`; XML dans `ISAPIClient.parse_event_notification`.

Constats précis :

- `EventNotificationsView` est une vue HA sans authentification, enregistrée par `hass.http.register_view()` dans `__init__.py`. Elle n'est pas un serveur dédié et n'est pas désenregistrée à l'unload.
- `parse_event_request()` lit le corps entier. Seuls `application/xml`, `application/xml; charset="UTF-8"` et `text/xml` sont traités comme XML. Tout autre Content-Type est passé à `MultipartDecoder`.
- Les parties multipart XML exactes sont lues; une partie `image/jpeg` est seulement journalisée (`image found`). Le code d'écriture de fichier est commenté : aucun JPEG n'est conservé ni exposé.
- `EventNotificationAlert` est converti en `AlertInfo`: event type, channel, IO port, MAC, `detection_target` et `region_id`. Les cibles `human` et `vehicle` existent uniquement dans le bus event; il n'existe pas de binary sensor spécifique personne/véhicule.
- L'activation ne fait que mettre l'entité à `on`. Aucun chemin dans ce module ne rétablit `off`; le test ne couvre pas le retour à l'état inactif.
- Pour une alerte NVR dont `channel_id > 32`, le code cherche une caméra IP ayant `input_port == channel_id - 32`, sinon soustrait 32. Ce comportement est utile mais dépend de cette convention Hikvision.
- Avec `Missing 'Host' header in request`, aiohttp récent rejette une requête HTTP/1.1 invalide avant `EventNotificationsView.post()`. Ce problème ne peut pas être corrigé dans `parse_event_request`; il requiert le listener de compatibilité restreint prévu à la phase 3.
- Avec XML étiqueté `application/x-www-form-urlencoded`, aiohttp peut transmettre la requête, mais le code l'envoie à `MultipartDecoder`, qui échoue; l'exception est absorbée et la réponse reste HTTP 200. C'est une correction de parser/transport à faire côté intégration.
- Le header Content-Type absent provoque lui aussi une exception (`None.strip()`), absorbée puis HTTP 200. Il n'y a ni limite explicite de payload/header, ni timeout, ni validation d'origine réseau au niveau de la vue.

## D. Home Assistant compatibility issues

| Priorité | Fichier(s) | Constat et impact |
| --- | --- | --- |
| Bloquant | `notifications.py` | Les requêtes sans Host sont rejetées par aiohttp avant le code. L'endpoint HA existant ne peut pas résoudre cette incompatibilité. |
| Important | `notifications.py` | Mauvais Content-Type XML, Content-Type absent et multipart non conforme échouent puis retournent 200; les JPEG sont jetés. |
| Important | `__init__.py`, `notifications.py` | Vue HTTP enregistrée une seule fois, sans cycle de vie explicite; `get_first_instance_unique_id()` indexe la première entry active sans garde. Risque unload/reload et toutes entries désactivées. |
| Important | `binary_sensor.py`, `switch.py`, `camera.py`, `image.py` | Entity IDs forcés; les binary/switch utilisent même l'entity ID complet comme unique ID. Cela est fragile pour le registry et les migrations. |
| Important | `__init__.py` | Migration v1→v2 assigne directement `config_entry.version = 2` au lieu de persister via `async_update_entry`; à vérifier face aux APIs HA ciblées. |
| Important | `notifications.py` | `socket.gethostbyname()` est synchrone dans le handler async; une résolution DNS peut bloquer la boucle HA. |
| Important | `services.py` | `isapi_request` accepte méthode, path et payload arbitraires pour toute entry identifiée; utile mais large, à conserver seulement avec validation/documentation claire. |
| Mineur | `image.py` | Lecture synchrone de fichier dans `ImageEntity.image`; le modèle actuel est un pointeur vers une image sur disque, pas une image d'événement en mémoire. |
| Mineur | `diagnostics.py` | Diagnostics utiles mais pas de statut listener/compteurs d'événements; certaines erreurs sont renvoyées comme objets exception non sérialisables. |
| Mineur | `config_flow.py` | Pas d'Options Flow pour les réglages avancés; reconfigure/reauth sont présents et modernes. |
| Cosmétique | `diagnostics.py` | Docstring résiduelle «Wiser». |

Points conformes : usage async de `httpx` et du client HA, `ConfigEntry.runtime_data` typé, forwarding async des plateformes, `DataUpdateCoordinator`, device registry et reauth/reconfigure. Aucun usage de `hass.data` n'a été trouvé dans le code de l'intégration.

## E. NVR architecture

Le NVR est détecté lorsque la somme des entrées analogiques et IP annoncées par `System/capabilities` dépasse 1. Les caméras IP proviennent de `ContentMgmt/InputProxy/channels`; les analogiques de `System/Video/inputs/channels`. Chaque caméra obtient ses streams par `Streaming/channels/{canal}0{type}` : `101` main, `102` sub, `103` third, `104` transcoded.

Les canaux deviennent des devices enfants via `via_device=(DOMAIN, nvr_serial)` pour un NVR. Les caméras IP conservent firmware, IP/port et serial; les analogiques ont un serial synthétique `{nvr_serial}-VI{canal}`. Pour une caméra proxifiée dont le serial manque ou est dupliqué, le fork hérite du correctif amont : `{nvr_serial}_{proxyProtocol}_{camera_id}`. Ce mécanisme et les relations parent/enfant doivent impérativement être préservés.

Forces à conserver : discovery séparée IP/analogique, serial de secours pour les proxys, streams par canal, support des caméras multi-canaux standalone (canaux tirés de `Streaming/channels`) et mapping d'événement >32.

Fragilités : l'heuristique NVR basée sur le nombre d'entrées, le fallback `channel-32`, la réutilisation possible du serial du device pour une standalone multi-channel, et l'absence de tests de snapshot/événement multipart par canal NVR.

## F. ISAPI architecture

`isapi/isapi.py` concentre les requêtes, l'authentification Basic/Digest, XML (`xmltodict`), timeouts (20 s) et la plupart des endpoints. `HikvisionDevice` ajoute la logique HA. La session est `httpx.AsyncClient` obtenue via `homeassistant.helpers.httpx_client`.

| Méthode | Endpoint | Fonction | Usage |
| --- | --- | --- | --- |
| GET | `System/deviceInfo` | `get_device_info` | identité, modèle, serial, firmware, MAC |
| GET | `System/capabilities` | `get_hardware_info` | entrées, sorties, vacances, channel zero, mutex |
| GET | `Streaming/channels`, `Streaming/channels/{id}` | `get_cameras`, `get_camera_streams` | discovery et résolution/codec des streams |
| GET | `ContentMgmt/InputProxy/channels` | `get_cameras` | canaux IP derrière NVR |
| GET | `System/Video/inputs/channels` | `get_cameras` | canaux analogiques |
| GET | `Event/triggers`, `Event/channels/capabilities` | `get_supported_events` | événements et multi-channel |
| GET/PUT | URL événement dérivée | `get/set_event_enabled_state` | état/activation détection |
| GET/PUT | `Event/notification/httpHosts` | `get/set_alarm_server` | destination `/api/hikvision` |
| GET | `ContentMgmt/Storage` | `get_storage_devices` | HDD/NAS |
| GET/PUT | `System/IO/outputs/{n}/status|trigger` | `get_io_port_status`, `set_output_port_state` | sorties alarme |
| GET/PUT | `System/Holidays` | `get/set_holiday_enabled_state` | mode vacances |
| GET | `Security/adminAccesses` | `get_protocols` | port RTSP |
| GET | `Streaming/channels/{id}/picture` | `get_camera_image` | snapshot, fallback StreamingProxy |
| PUT | `System/reboot` | `reboot` | action reboot |
| POST | `System/mutexFunction?format=json` | `get_event_switch_mutex` | éviter des détections incompatibles |

Les erreurs 401/403 sont normalisées; les autres erreurs HTTP remontent et sont capturées par les callers/coordinators. `request_bytes()` n'appelle pas `raise_for_status()`, donc un statut HTTP d'erreur peut devenir un snapshot; à couvrir avant tout changement. Les logs debug peuvent inclure les payloads ISAPI : ne pas les activer sans précaution, car certains XML sont sensibles.

## G. Capability detection

La détection est partielle mais réelle, principalement dans `get_hardware_info()` :

- `System/capabilities` : nombre d'entrées analogiques/IP, input/output ports, holiday, channel zero, mutex, PIR.
- Présence/réponse de `Event/notification/httpHosts` : support Notification Host.
- `Event/triggers` et, en multi-channel, `Event/channels/capabilities` avec attribut `@opt` : événements disponibles.
- Fallback spécifique scene-change après vérification `SmartCap.isSupportSceneChangeDetection`.
- `Security/adminAccesses` : port RTSP.
- Les entités sorties, holiday et événements sont créées conditionnellement à ces résultats.

Limites : `CapabilitiesInfo` ne représente ni PTZ, ni éclairage, ni sirène/audio, ni mode jour/nuit, ni contrôles d'image, ni Human/Vehicle. La caméra est considérée NVR par heuristique, et non par capability explicite. Aucun cache structuré ou rediscovery contrôlée n'existe au-delà du setup. Cette dataclass, la couche ISAPI et le mécanisme actuel de conditionnement d'entités sont la base à faire évoluer en phase 4, sans listes de modèles.

## H. Snapshot architecture

Chaque `HikvisionCamera` délègue à `ISAPIClient.get_camera_image(stream, width, height)`. Les streams ont déjà leur largeur/hauteur, lues depuis `Streaming/channels/{id}`. Si HA ne demande pas une largeur ≤100, le client envoie `videoResolutionWidth` et `videoResolutionHeight` vers `Streaming/channels/{id}/picture`; il bascule vers `ContentMgmt/StreamingProxy/channels/{id}/picture` sur le XML d'erreur «Invalid XML Content» et réessaie jusqu'à deux fois sur «Device Error».

Le support HD est donc partiellement déjà présent. Le futur correctif doit être implémenté dans `get_camera_image()`/la sélection de `CameraStreamInfo`, après avoir confirmé sur équipements réels les endpoints qui ignorent les paramètres. Il faut conserver le stream main (`type_id == 1`) par caméra/canal et le fallback proxy. Aucune image d'événement multipart n'alimente `image.py` : cette plateforme ne lit qu'un fichier défini par le service `update_snapshot_filename`.

## I. Test coverage

Tests existants :

- Unit/ISAPI : `tests/test_isapi.py`, fixtures XML Storage et Notification Host.
- Config flow : `tests/test_config_flow.py` (création, auth/permissions, reconfigure, reauth).
- Setup/intégration : `tests/test_init.py` sur 15 modèles NVR/DVR/caméras, load/unload et alarm host.
- Événements : `tests/test_notifications.py` (NVR, standalone, multi-channel thermique, MAC/IP, `detection_target` Human/Vehicle).
- Camera/NVR : `tests/test_camera.py` (streams, snapshot normal, erreurs, endpoint alternatif, multi-channel, serial proxy dupliqué).
- Entités : `test_sensor.py`, `test_switch.py`, `test_pir.py`, `test_services.py`.

Manques critiques : vraie requête HTTP sans Host, XML labelisé form-urlencoded, Content-Type absent, multipart XML, multipart XML+JPEG, requêtes malformées/surdimensionnées, expiration off des binary sensors, cycle de vie listener, source non autorisée, entity-ID/unique-ID migration complète, diagnostics, timeout/HTTP error du snapshot, et comportement NVR sur mapping événement/snapshot par canal.

Vérification effectuée : `python -m compileall -q custom_components tests` réussit. Exécution pytest : non effectuée faute de dépendances installées; la commande pip a été interrompue après blocage réseau.

## J. Technical debt

À traiter, par ordre d'utilité : transport d'événements incompatible et parseur trop strict; séparation transport/parser/états HA; sécurité/limites du listener; unique IDs et entity IDs forcés; cycle de vie de la vue; normalisation d'erreurs du client bytes; capability registry limité; diagnostics événementiels; puis tests de non-régression. Aucun refactor de style isolé n'est recommandé.

## K. Recommended implementation order

1. Phase 1 : installer/exécuter la suite, figer les régressions d'identité et de setup/unload, corriger les APIs HA clairement obsolètes sans changer les unique IDs existants.
2. Phase 2 : extraire un parser pur XML/multipart vers un événement normalisé; conserver la vue actuelle comme adaptateur temporaire.
3. Phase 3 : ajouter le listener de compatibilité `asyncio.start_server` strictement limité; tests missing Host, MIME erroné, multipart, tailles et méthodes.
4. Phase 4 : étendre `CapabilitiesInfo` en registre de capabilities, à partir de réponses/sondes ISAPI.
5. Phases 5–7 : Human/Vehicle, image d'événement en mémoire, snapshots HD; préserver le mapping NVR.
6. Puis phases 8–15 du document de référence, chaque groupe piloté par capabilities.

## L. Files likely to change in Phase 1

- `custom_components/hikvision_next/__init__.py` : unload/migration/lifecycle de vue.
- `custom_components/hikvision_next/binary_sensor.py`, `switch.py`, `camera.py`, `image.py`, `sensor.py` : stratégie compatible d'entity IDs et unique IDs.
- `custom_components/hikvision_next/hikvision_device.py` et `coordinator.py` : accès runtime/erreurs seulement si les tests révèlent une incompatibilité.
- `tests/test_init.py`, `test_sensor.py`, `test_camera.py`, `test_notifications.py` et nouvelles fixtures/tests de migration et lifecycle.
- Éventuellement `manifest.json` uniquement si une contrainte HA ou de dépendance est démontrée.

## M. Risks

| Risque | Maîtrise requise |
| --- | --- |
| Migrations | Ne jamais modifier un unique ID existant silencieusement. Prévoir migration explicite et tests de registry. |
| Unique IDs | Les binary/switch stockent actuellement un entity ID complet comme unique ID; dissocier cela peut créer des doublons sans migration. |
| NVR | Préserver serials de secours, `via_device`, canaux analogiques/IP et mapping stream/canal. |
| Events | Ne pas affaiblir aiohttp ni patcher HA; le listener legacy doit être borné, local et testé. |
| Compatibilité HA | Vérifier les APIs contre la version HA ciblée après installation des tests; ne pas confondre correction de parser et rejet aiohttp pré-handler. |
| Backward compatibility | Maintenir domaine `hikvision_next`, ConfigEntry data et topologie d'entités; introduire de nouvelles entités (Human/Vehicle/image événement) sans renommer les existantes. |
