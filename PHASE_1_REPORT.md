# Phase 1 Report — Home Assistant Compatibility Baseline

## Changes made

- Created the local branch `phase-1-ha-compat`.
- Moved registration of `EventNotificationsView` from `async_setup_entry` to the integration-level `async_setup`.
- Removed `get_first_instance_unique_id`, whose indexing could fail when every entry was disabled and whose use made view lifecycle depend on entry ordering.
- Removed mutable request state (`self.device`) from the shared HTTP view; the resolved device is now passed explicitly through channel mapping, binary-sensor update and HA-event emission.
- Moved hostname resolution in event device matching to `hass.async_add_executor_job`.
- Added `tests/test_lifecycle.py` with setup → unload → setup regression coverage for a NVR and a test ensuring hostname resolution is off the HA event loop.

No raw listener, aiohttp change, event parser refactor or new user-facing feature was added.

## Compatibility fixes

`EventNotificationsView` is registered once when Home Assistant sets up the integration domain, rather than during config-entry setup. Config-entry unload/reload no longer registers another view, and the view no longer retains the device from a previous request.

Hostname matching previously called `socket.gethostbyname` synchronously inside the HTTP request coroutine. DNS resolution now runs in Home Assistant's executor; direct IP comparisons remain immediate.

The existing runtime-data implementation was retained. It already uses typed `ConfigEntry[HikvisionDevice]` and `entry.runtime_data`, so a new runtime-data wrapper would add churn without compatibility value in this phase.

## Unique ID impact

**Unchanged.**

Existing unique IDs remain intact for all current platforms:

- camera: slugified device serial + stream ID;
- image: slugified serial + stream ID + `_snapshot`;
- binary sensor and event switch: historical full entity-ID-shaped unique ID;
- output/holiday switches and diagnostic sensors: existing deterministic formats.

The binary/switch format is not ideal, but changing it would create duplicate entities or require a registry migration. It is stable, deterministic and channel-aware, so it is intentionally deferred.

## Entity ID impact

**Unchanged.**

The fork's existing `1f25fa6` correction remains in place: diagnostic sensor entity IDs slugify serials containing `/`, `-`, uppercase and similar invalid characters; snapshot entities use the `image` domain.

The remaining manually assigned entity IDs are already built from slugified serial values. Removing them in this phase could rename existing entities. Their removal/migration needs a dedicated, tested compatibility decision rather than a style-only change.

## ConfigEntry lifecycle

Setup now performs domain-level service and HTTP-view registration once. Entry setup remains responsible for hardware discovery, device-registry creation, coordinators and platforms. Entry unload unloads platforms and resets the configured notification host when this integration owns it.

The added regression test records all entity and unique IDs for an NVR entry, unloads it, sets it up again, and asserts that both sets are exactly preserved. It also asserts that entry reload does not register another HTTP view.

## NVR compatibility

No NVR discovery, stream mapping, parent/child device registry relationship, proxy-camera serial fallback, channel mapping or snapshot logic was changed.

The lifecycle test uses the existing `DS-7608NXI-I2` fixture, which exercises NVR setup and every current platform before reload.

## Tests added

- `tests/test_lifecycle.py::test_nvr_setup_unload_reload_preserves_entities`
- `tests/test_lifecycle.py::test_event_hostname_resolution_uses_executor`

## Tests executed

| Command | Result |
| --- | --- |
| `C:\Users\Ivan Morgade\AppData\Local\Programs\Python\Python312\python.exe -m compileall -q custom_components tests` | PASS |
| `git diff --check` | PASS |
| `.venv\Scripts\python.exe -m pip install -r requirements.test.txt` | NOT RUN TO COMPLETION — resolver conflict between unpinned `pytest-cov>=4.1.0` and the current `pytest-homeassistant-custom-component` releases. |
| Explicit local compatible plugin install | NOT RUN TO COMPLETION — the old HA test stack entered a source build dependency (`Cython`) and remained blocked; the project-owned process was terminated. |
| `.venv\Scripts\python.exe -m pytest` | NOT RUN — pytest was not installed because dependency resolution/build did not complete. |

No dependency file was changed to force a test environment.

## Remaining known issues

Legacy Hikvision HTTP notifications without a `Host` header remain unsupported. This is intentionally deferred to Phase 3.

XML mislabelled as `application/x-www-form-urlencoded`, multipart JPEG retention, payload limits and the legacy listener's transport/parsing separation are also intentionally deferred to Phases 2 and 3.

The existing direct assignment of `config_entry.version` in the legacy migration and the historical binary/switch unique-ID shape remain candidates for a dedicated migration review; neither was changed without a proven migration path.

## Phase 2 readiness

The current boundaries are now clearer:

- transport and HTTP request reading: `custom_components/hikvision_next/notifications.py:EventNotificationsView.post`;
- request/multipart parsing: `EventNotificationsView.parse_event_request`;
- XML parsing: `custom_components/hikvision_next/isapi/isapi.py:ISAPIClient.parse_event_notification`;
- device/channel lookup and event state/HA event processing: `notifications.py`.

Phase 2 should extract the parser and normalized event processing from `notifications.py` while preserving the externally visible entities, unique IDs and NVR channel mapping.
