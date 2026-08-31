# Phase 2 Report — Event Architecture Refactor

## Architecture before

`EventNotificationsView` recevait la requête aiohttp, lisait le body, interprétait le Content-Type, décodait le multipart, parseait `EventNotificationAlert`, retrouvait la config entry, corrigeait les canaux NVR, mettait à jour le binary sensor et publiait l'événement HA.

Le parsing XML d'événements était une méthode statique de `ISAPIClient`, ce qui mélangeait les requêtes ISAPI avec les notifications push.

## Architecture after

```text
aiohttp transport (notifications.py)
  → body, Content-Type, source IP
  → HikvisionEventPayloadParser (events.py)
  → HikvisionEventParser
  → HikvisionEvent (dataclass)
  → HikvisionEventProcessor
  → binary sensor + hikvision_next_event
```

`EventNotificationsView.post()` est maintenant un adaptateur mince : lecture de la requête, logs bornés, délégation et réponse HTTP existante. Le parser ne prend aucun objet aiohttp et le processor ne dépend ni de headers, ni de multipart, ni de `web.Request`.

## Files changed

- `custom_components/hikvision_next/events.py` — nouveau modèle, exceptions, extraction XML/JPEG, parsing XML, résolution device/canal et application HA.
- `custom_components/hikvision_next/notifications.py` — réduit au transport HTTP.
- `custom_components/hikvision_next/isapi/isapi.py` — suppression du parser de notifications push.
- `custom_components/hikvision_next/isapi/models.py` et `isapi/__init__.py` — suppression de l'ancien `AlertInfo`.
- `tests/test_events.py` — nouveaux tests de parser et processor.
- `tests/test_lifecycle.py` — test DNS de phase 1 adapté au processor.

## Event model

`HikvisionEvent` est une dataclass à slots avec les champs réellement extraits :

- `event_id`
- `channel_id`
- `io_port_id`
- `device_serial_no`
- `device_mac`
- `device_ip`
- `region_id`
- `detection_target`
- `event_state`

`ParsedEventPayload` contient l'XML et, si présent, les bytes JPEG. L'image est retenue uniquement en mémoire pendant le parsing : aucune entité image, écriture disque ou fonctionnalité utilisateur n'a été ajoutée.

## Multipart handling

Le parser inspecte le Content-Type, mais priorise le sniffing XML pour les équipements Hikvision qui étiquettent mal le payload. Il gère `application/xml`, `text/xml`, XML sous `application/x-www-form-urlencoded` et `multipart/*`.

Dans un multipart, chaque partie est inspectée indépendamment de l'ordre : la partie XML est extraite et une partie JPEG est conservée dans `ParsedEventPayload.image`. Les JPEG ne sont ni journalisés, ni transformés, ni persistés.

## NVR behavior

Le processor a repris à l'identique le comportement précédent :

- une seule config entry est utilisée directement ;
- plusieurs entries sont résolues par MAC puis adresse IP source, avec DNS dans l'executor HA ;
- les canaux supérieurs à 32 sont mappés à la caméra IP par input port, avec le fallback `channel - 32`;
- le même unique ID historique est recherché pour le binary sensor ;
- les relations NVR/canaux, streams, devices et entity IDs ne sont pas modifiés.

## HA event compatibility

Compatible :

- nom : `hikvision_next_event` inchangé ;
- clés historiques : `channel_id`, `io_port_id`, `camera_name`, `event_id` inchangées ;
- clés conditionnelles `detection_target` et `region_id` inchangées ;
- valeurs et mapping de canal préservés.

Aucun domain, ConfigEntry data, unique ID, entity ID, device registry identifier, nom d'entité ou service n'a été modifié.

## Tests added

- XML `application/xml` et `text/xml` → payload puis événement normalisé.
- XML `application/x-www-form-urlencoded` → sniffing XML rétrocompatible.
- Multipart avec JPEG avant XML → XML extrait et JPEG conservé.
- Motion, intrusion et line crossing → event IDs normalisés.
- Malformed XML → `HikvisionEventParseError` contrôlée.
- Processor NVR → même binary sensor et même payload HA event.
- Test lifecycle Phase 1 adapté : DNS hostname dans l'executor du processor.

## Tests executed

| Command | Result |
| --- | --- |
| `C:\Users\Ivan Morgade\AppData\Local\Programs\Python\Python312\python.exe -m compileall -q custom_components tests` | PASS |
| `git diff --check` | PASS |
| `.venv\Scripts\python.exe -m pip install -r requirements.test.txt` (Phase 1) | FAIL — resolver actuel ne trouve pas de combinaison avec la contrainte non épinglée. |
| Installation locale explicitement compatible (`pytest-homeassistant-custom-component==0.13.179`, HA 2024.11.0b5, pytest 8.3.3, pytest-cov 5.0.0, Python 3.12) | NOT COMPLETED — dépendance source Cython bloquée pendant le build ; processus arrêté et environnement supprimé. |
| `C:\Users\Ivan Morgade\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q` | NOT AVAILABLE — `No module named pytest`, la stack Home Assistant de test n'est pas installée. |

`requirements.test.txt` n'a pas été modifié. La combinaison cohérente identifiée est celle imposée par `pytest-homeassistant-custom-component==0.13.179`; un futur correctif de pinning devra être séparé et validé, plutôt que changé silencieusement pendant ce refactor.

## Known limitations

HTTP/1.1 requests without Host are still rejected by aiohttp. This is intentionally deferred to Phase 3.

Le transport aiohttp existant continue de répondre HTTP 200 après une erreur de parsing, afin de conserver le comportement historique. La politique de réponse et les limites réseau relèvent du listener de phase 3.

## Phase 3 readiness

Un listener raw peut désormais extraire seulement `body`, `content_type` et `source_ip`, puis appeler :

```python
payload = HikvisionEventPayloadParser().parse(body, content_type)
event = HikvisionEventParser().parse(payload.xml)
await HikvisionEventProcessor(hass).async_process(event, source_ip)
```

Aucune dépendance à `aiohttp.web.Request`, à `MultipartDecoder` dans le transport ou à l'état mutable d'une vue HTTP ne subsiste dans le processor.
