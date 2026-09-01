**# Phase 6 Report — Automatic High-Resolution Snapshots**

**## Files changed**

**### Production code**

\| File | Change |

\|---|---|

\| \`custom\_components/hikvision\_next/isapi/isapi.py\` | Refactored \`get\_camera\_image\` to add legacy-request fallback and unknown-resolution handling; extracted \`\_fetch\_camera\_image\` (error-recovery helper) and \`\_has\_known\_resolution\` (static check). |

**### Tests**

\| File | Change |

\|---|---|

\| \`tests/test\_snapshot.py\` | **\*\*New file\*\*** — 16 Windows-compatible tests covering all Phase 6 scenarios. |

No changes were made to \`camera.py\`, \`hikision\_device.py\`, \`models.py\`, entity IDs, unique IDs, domain, event handling, Human/Vehicle sensors, or the legacy HTTP listener.

**## Resolution discovery method**

The main-stream resolution is discovered during integration setup in

\`ISAPIClient.get\_camera\_streams()\` (\`isapi/isapi.py:358\`), which iterates over

\`STREAM\_TYPE\` (1=Main, 2=Sub, 3=Third, 4=Transcoded) for each camera channel and

fetches \`Streaming/channels/{channel\_id}0{stream\_type\_id}\`.  From each response it

reads:

\* \`videoResolutionWidth\` → \`CameraStreamInfo.width\`

\* \`videoResolutionHeight\` → \`CameraStreamInfo.height\`

The resulting \`CameraStreamInfo\` objects are stored on each \`IPCamera\` /

\`AnalogCamera\` and are **\*\*cached\*\*** — \`get\_camera\_streams\` is only called during

\`get\_hardware\_info()\` (setup), never on snapshot requests.

When \`get\_camera\_image()\` is called it reads the cached resolution from the

\`CameraStreamInfo\` that was already constructed during setup.  No stream

configuration is queried on every snapshot request.

**## NVR mapping behavior**

NVR / channel mapping is unchanged from the existing \`get\_cameras()\` logic:

\* **\*\*NVR cameras\*\*** (IP-proxied): discovered via \`ContentMgmt/InputProxy/channels\`;

  each camera retains its own \`CameraStreamInfo\` list fetched from

  \`Streaming/channels/{camera\_id}0{stream\_type\_id}\`.

\* **\*\*Analog cameras\*\***: discovered via \`System/Video/inputs/channels\`.

\* **\*\*Standalone cameras\*\***: discovered via \`Streaming/channels\` with

  \`connection\_type=CONNECTION\_TYPE\_DIRECT\`.

Each camera's main stream has \`type\_id == 1\`.  Because resolution is stored per

\`CameraStreamInfo\`, \*\*different NVR channels automatically get different

resolutions\*\* — no special per-channel logic is required.

Verified from fixture data:

\| Device | Channel | Stream | Resolution |

\|---|---|---|---|

\| DS-2CD2386G2-IU (standalone) | 1 | 101 | 3840×2160 |

\| DS-2CD2532F-IWS (standalone) | 1 | 101 | 1920×1080 |

\| DS-7608NXI-I2 (NVR) | 1 | 101 | 3840×2160 |

\| DS-7608NXI-I2 (NVR) | 3 | 301 | 1920×1080 |

\| DS-7732NI-M4 (NVR) | 1 | 101 | 3072×2048 |

\| DS-7732NI-M4 (NVR) | 4 | 401 | 3840×2160 |

**## Fallback behavior**

\`get\_camera\_image()\` now follows a two-phase strategy:

**### Phase 1 — High-resolution request (with params)**

If the stream resolution is known (both width and height > 0) and HA requests a

full-size image (width is \`None\` or > 100), the snapshot is fetched with

explicit \`videoResolutionWidth\` / \`videoResolutionHeight\` query parameters

matching the cached main-stream resolution.

If the resolution is unknown (0, \`"0"\`, \`None\`, or missing), no parameters are

sent — the device's default resolution is used.

**### Phase 2 — Legacy fallback (without params)**

If Phase 1 returns an ISAPI error response (any XML starting with \`\<?xml \`)

after all existing error-recovery retries are exhausted (alternate URL switch

for statusCode 6, up to 2 retries for statusCode 3), \`get\_camera\_image\`

automatically retries **\*\*without\*\*** resolution parameters — the legacy request.

Conditions for fallback to trigger:

\* The response starts with \`\<?xml \` (ISAPI error).

\* HA requested a full-size image (not a thumbnail).

\* \`attempt == 0\` (initial call, not already a retry).

\* The stream has a known resolution (i.e. params were actually sent in the

  first place — no point falling back if no params were used).

The fallback call uses \`attempt=99\` to prevent recursive retries inside

\`\_fetch\_camera\_image\`.

**### Existing error recovery (unchanged)**

\* **\*\*statusCode 6\*\*** (Invalid XML Content): switches to

  \`ContentMgmt/StreamingProxy/channels/{id}/picture\` and retries.

\* **\*\*statusCode 3\*\*** (Device Error): retries up to 2 times.

\* **\*\*Thumbnail requests\*\*** (width ≤ 100): params are never sent, so no

  high-resolution/fallback logic is engaged.

**## Tests**

File: \`tests/test\_snapshot.py\` — 16 tests, all passing.

Tested scenarios (mapped to AUDIT\_PHASE\_6 requirements):

\| Requirement | Test | Result |

\|---|---|---|

\| 1920×1080 stream | \`test\_snapshot\_1920x1080\_sends\_resolution\_params\` | ✅ |

\| 3840×2160 stream | \`test\_snapshot\_3840x2160\_sends\_resolution\_params\` | ✅ |

\| Missing/invalid resolution | \`test\_snapshot\_missing\_resolution\_sends\_no\_params\`, \`test\_snapshot\_string\_zero\_resolution\_sends\_no\_params\`, \`test\_snapshot\_no\_fallback\_when\_resolution\_unknown\` | ✅ |

\| Standalone camera | \`test\_snapshot\_standalone\_camera\`, \`test\_resolution\_discovery\_from\_device\_fixture\_standalone\` | ✅ |

\| Two NVR channels with different resolutions | \`test\_snapshot\_nvr\_channels\_different\_resolutions\`, \`test\_resolution\_discovery\_from\_device\_fixture\_nvr\_channels\` | ✅ |

\| Explicit-resolution request failure → legacy fallback | \`test\_snapshot\_fallback\_to\_legacy\_on\_device\_error\`, \`test\_snapshot\_fallback\_to\_legacy\_on\_invalid\_xml\_content\` | ✅ |

Additional coverage:

\| Test | Description |

\|---|---|

\| \`test\_snapshot\_int\_resolution\_sends\_params\` | Integer resolution values are handled |

\| \`test\_snapshot\_respects\_ha\_requested\_width\` | HA-requested width > 100 still sends stream resolution |

\| \`test\_snapshot\_no\_fallback\_on\_thumbnail\_request\` | Thumbnail requests (width ≤ 100) never trigger fallback |

\| \`test\_snapshot\_uses\_cached\_resolution\_not\_re\_fetched\` | Multiple calls use cached resolution without re-fetching |

**### Run command and results**

\`\`\`

python -m pytest tests/test\_snapshot.py -q

16 passed

\`\`\`

**## Real hardware validation**

Not performed in this session (no remote HA instance / camera access available).

Validation was performed at the unit-test level using cached fixture data from

real Hikvision devices:

\* Standalone cameras: DS-2CD2386G2-IU, DS-2CD2532F-IWS

\* NVR: DS-7608NXI-I2, DS-7732NI-M4 (18 channels with varying resolutions)

**## Known limitations**

1\. **\*\*Event-attached JPEG images\*\***: Out of scope for this phase.  Event images

   are explicitly excluded per the audit ("Do not mix this with event-attached

   JPEG images.  Those are a separate feature.").

2\. **\*\*No real HTTP verification on Windows\*\***: The async integration tests that

   use \`respx\` + \`init\_integration\` (e.g. \`tests/test\_camera.py\`) cannot run on

   this Windows environment due to the pre-existing \`pytest\_socket\` event-loop

   conflict (documented in Phase 5 report).  Snapshot tests in this phase use a

   Windows-compatible pattern (mock \`request\_bytes\` directly, run via

   \`\_run\_async\`) to avoid the issue.

3\. **\*\*Resolution stored as string from XML\*\***: \`deep\_get\` returns string values

   from the ISAPI XML response (e.g. \`"3840"\`).  The \`get\_camera\_image\` method

   now converts to \`int()\` before comparison and before sending as query

   parameters.  HTTP serialization is identical regardless (httpx converts both

   to strings in the URL).

4\. **\*\*Multiple simultaneous snapshots\*\***: The \`use\_alternate\_picture\_url\` flag is

   mutated on the shared \`CameraStreamInfo\` instance.  In a concurrent

   scenario (multiple HA snapshot requests in parallel), the flag could be set

   by one request and observed by another.  This matches pre-existing behavior

   and was not introduced by this phase.