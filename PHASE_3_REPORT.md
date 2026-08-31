# Phase 3 Report — Legacy Hikvision HTTP Listener

## Listener architecture

`custom_components/hikvision_next/legacy_http.py` introduit `HikvisionLegacyHttpListener`.

```text
asyncio.start_server
  → parse HTTP request line + headers + Content-Length
  → HikvisionEventPayloadParser
  → HikvisionEventParser
  → HikvisionEventProcessor
```

Le listener ne contient aucun parsing XML, multipart, JPEG, device lookup ou mapping NVR. Il ne dépend pas d'aiohttp. Chaque connexion conserve son body et sa source IP localement, puis est fermée après une seule réponse.

## HTTP compatibility

Confirmé par les nouveaux tests socket bruts :

- `POST /api/hikvision HTTP/1.1` sans header `Host` est accepté ;
- HTTP/1.0 est accepté ;
- HTTP/1.1 avec `Host` reste accepté ;
- `Content-Type` est traité sans sensibilité à la casse dans le transport ;
- XML étiqueté `application/x-www-form-urlencoded` est délégué au sniffing de phase 2 ;
- multipart XML + JPEG est délégué sans inspection du JPEG par le listener.

La restriction aiohttp sur `Host` ne s'applique pas à ce transport asyncio.

## Port and binding

- Bind par défaut : `0.0.0.0`
- Port par défaut : `8124`
- Route unique : `POST /api/hikvision`

Les nouvelles configurations proposent `http://<adresse-HA>:8124/api/hikvision` comme Notification Host. Les entrées existantes conservent leur URL persistée, notamment `8123`, et le transport aiohttp historique reste disponible sur Home Assistant.

Un conflit de port est journalisé clairement et ne bloque pas le chargement de l'intégration.

## Limits

| Limite | Valeur | Raison |
| --- | ---: | --- |
| Headers | 16 KiB | Bloquer les requêtes non bornées avant parsing. |
| Payload | 16 MiB | Laisser place aux multipart XML + JPEG Hikvision tout en bornant la mémoire. |
| Timeout headers | 10 s | Éviter les sockets lentes inactives. |
| Timeout body | 10 s | Éviter les Content-Length incomplets. |
| Connexions simultanées | 20 | Volume très supérieur aux notifications normales, sans file d'attente non bornée. |
| Keep-alive | désactivé | Une requête et une connexion par notification. |

## Error policy

| Cas | Réponse |
| --- | --- |
| HTTP invalide / Content-Length invalide / corps incomplet | 400 |
| Méthode autre que POST | 405 |
| Route autre que `/api/hikvision` | 404 |
| Headers trop grands | 431 |
| Payload trop grand | 413 |
| `Transfer-Encoding` (dont chunked) | 501 |
| Timeout lecture | 408 |
| POST valide mais événement non reconnu | 200 + warning |
| Erreur interne inattendue | 500 |

Le 200 pour un event non reconnu conserve la politique historique, afin d'éviter les retry storms de certains firmwares Hikvision. Les erreurs de transport restent explicitement rejetées.

## Security

Le listener n'est pas un serveur HTTP généraliste :

- route et méthode uniques ;
- `Host` volontairement facultatif, mais aucun routage virtuel ;
- headers/payload/timeouts/concurrence bornés ;
- aucun proxy, keep-alive, TLS, chunked, GET, OPTIONS ou autre méthode ;
- le processor ne traite un événement que s'il peut résoudre une intégration connue.

Il est destiné au LAN de confiance ; une allowlist IP obligatoire aurait cassé les NVR/proxy-caméras dont la source peut différer de l'hôte configuré.

## Lifecycle

Le listener est créé une seule fois dans `async_setup`, à côté de la vue aiohttp de phase 1. Il démarre avec l'intégration au niveau Home Assistant, pas avec une ConfigEntry. Un handler `EVENT_HOMEASSISTANT_STOP` ferme le serveur et attend la libération du socket dans une tâche HA.

`async_start()` est idempotent. `async_stop()` est idempotent et le test couvre start → stop → start sur le même port.

## NVR compatibility

Aucune logique NVR n'a changé. Le listener transmet simplement `source_ip` au `HikvisionEventProcessor` de phase 2, qui conserve la résolution par MAC/IP, le mapping supérieur à 32 et les unique/entity IDs historiques.

## aiohttp transport

`EventNotificationsView` sur le port Home Assistant (`8123`) reste inchangé et continue d'utiliser les mêmes parser et processor de phase 2. Le port `8124` ne sert qu'aux notifications legacy sans `Host`.

## Tests added

`tests/test_legacy_http.py` couvre :

- HTTP/1.1 sans Host, HTTP/1.0 et Host classique ;
- MIME form-urlencoded contenant XML ;
- multipart XML + JPEG avec rétention interne ;
- événement non reconnu acknowledged 200 ;
- méthode, route, Content-Length et Transfer-Encoding non supportés ;
- headers et payload surdimensionnés ;
- body incomplet ;
- concurrence de trois notifications ;
- cycle start/stop/start.

## Tests executed

| Command | Result |
| --- | --- |
| `C:\Users\Ivan Morgade\AppData\Local\Programs\Python\Python312\python.exe -m compileall -q custom_components tests` | PASS |
| `git diff --check` | PASS |
| `C:\Users\Ivan Morgade\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q` | NOT AVAILABLE — `No module named pytest`. |
| Installation de `requirements.test.txt` | Non complétée pendant les phases 1–2 : conflit de résolution, puis dépendance Cython bloquée. Aucun pinning n'a été modifié ici. |

## Known limitations

- Pas de `Transfer-Encoding: chunked`.
- Pas de TLS : usage LAN dédié.
- Pas de keep-alive.
- L'allowlist des IP n'est pas imposée, car la résolution par processor doit conserver les NVR/proxy-caméras.
- Le listener ne crée pas encore d'entités diagnostics ; les compteurs restent internes.
- La configuration avancée du port est reportée à un futur Options Flow.

## Phase 4 readiness

La phase 4 pourra ajouter une découverte de capabilities au client ISAPI et conditionner les entités sans modifier le transport : les événements, le listener legacy, le transport aiohttp et le processor sont désormais isolés des futures capabilities.
