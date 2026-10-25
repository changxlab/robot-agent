# Source register and research coverage

Snapshot checked **2026-10-25**. Public official Unitree pages and official
`unitreerobotics` repositories only. All research is summarized/paraphrased;
this bundle is not a redistribution of Unitree manuals.

## Sources actually read

| ID | Official source | Revision evidence | Coverage |
|---|---|---|---|
| S1 | [B2 product page](https://www.unitree.com/b2) | No reliable content-revision date displayed; retrieved 2026-10-25 | Performance claims, specification table and qualifications; HTML text |
| S2 | [About B2](https://support.unitree.com/home/en/B2_developer/About%20B2) | Page says 2026-06-30 | Rendered article: component descriptions, electrical budgets/pinout table, joints, robot and battery specs |
| S3 | [Obtain SDK](https://support.unitree.com/home/en/B2_developer/Obtain%20SDK) | Page says 2026-07-30 | Download/model entry page; not all linked archives examined |
| S4 | [SLAM and Navigation Services Interface](https://support.unitree.com/home/en/B2_developer/SLAM%26Navigation%20Interface) | Page says 2024-04-03 | Rendered full article: legacy PC2/lidar setup, IDL, topics, command table and feedback semantics |
| S5 | [Overview of SLAM Navigation Service](https://support.unitree.com/home/en/navigation/SLAM%26Navigation_service) | Page says 2026-09-16 13:31:05, timezone unspecified | Rendered sections 1.1-1.8: positioning, capabilities, modes, specifications, compatibility, precautions and positioning options |
| S6 | [SDK2 pinned tree](https://github.com/unitreerobotics/unitree_sdk2/tree/d1abf001220d3e5f59e00a0c4aaa595e00089a4a) | Commit `d1abf001220d3e5f59e00a0c4aaa595e00089a4a`, 2026-10-15T10:02:51Z | README, B2 example and relevant B2 sport/state/motion-switcher headers, channel initialization; not all repository files |
| S7 | [ROS 2 pinned README](https://github.com/unitreerobotics/unitree_ros2/blob/668d1ec5a05d1c38d3306bdca7d59f2ba3581a88/README.md) | Branch head `668d1ec5a05d1c38d3306bdca7d59f2ba3581a88`, 2026-07-02T12:45:43Z | B2 support, OS/ROS matrix, CycloneDDS, NIC/IP setup, state and request surfaces; examples not executed |
| S8 | [unitree_slam README](https://github.com/unitreerobotics/unitree_slam/blob/main/README.md) | Unpinned live read on snapshot date | Short build example targeting H1; no B2 compatibility conclusion |
| L1 | Existing robot-agent skills and base/mapping/configuration/loader code | Local read 2026-10-25; no firmware or hardware inspection | Wrapper capabilities, local limits, mapping differences and skill discovery; not vendor evidence |

Dates above are page labels or commit timestamps, not dates of installation,
release certification or proof of support for the physical robot.
A footer copyright year is **not** a revision date; different official pages
can display different footer years.

## Coverage limitations: not "all documentation"

This is a bounded primary-source survey. It does **not** certify that every
latest Unitree B2 or Navigation Solution document has been read.

- The public developer pages found were About B2, Obtain SDK and the legacy
  SLAM/navigation interface. The Software Interface Services category rendered
  as an empty landing page. Search/probing did not establish an exhaustive
  sidebar inventory.
- Navigation overview sections 1.1-1.8 were read. Additional detailed web
  operation guides, HTTP endpoint/WebSocket schemas, authentication/ports,
  installation packages, release notes and delivery-specific manuals were not
  comprehensively enumerated or read.
- Mechanical diagrams embedded as images were not dimensionally transcribed.
  The skill does not supply fabricated mounting coordinates or connector
  mating-face orientations.
- SDK/download archives, URDF/STEP files, all SDK implementations and all
  branches/releases were not exhaustively audited.
- No login-protected customer material, purchase/license entitlement,
  serial-number interpretation or installed firmware was verified.
- No real robot tests, network changes, controller calls, service changes or
  navigation launches were performed.

Direct support-site asset retrieval encountered a WAF block; support content
was instead read through its rendered public browser pages. A failed raw
download is not evidence that the rendered document is unavailable.

## Important corrections after source cross-checking

These details were verified against article text rather than relying on search
summaries or initial research notes:

1. Product battery figures differ from the developer manual; retain both.
2. Legacy feedback is semicolon/key-value formatted, not slash-delimited.
3. Legacy loop codes 10 and 11 mean all default nodes versus supplied nodes,
   not an unverified direction variant.
4. The navigation mapping range is not explicitly called a radius.
5. LiDAR/visual fusion is optional, not established as the default.
6. Tunnel mode requires optional XT32 lidar plus scanner/feature-processing
   prerequisites; RTK needs additional hardware/connectivity/services.
7. `GaitHeight` accepts a boolean in the inspected B2 SDK header.
8. >6 m/s is special-configuration performance; it is not established as the
   ordinary manual/teleoperation envelope.

## Refresh procedure

1. Reopen S1-S5 and record actual page revisions plus retrieval date. Review
   model/options notes, footnotes and newly linked detailed guides.
2. Resolve the SDK/ROS branch heads and compare B2 headers/messages against
   the installed firmware and deployment, not just the newest repository.
3. Obtain version-matched Navigation Solution operation and protocol guides.
   Verify eligibility, license, supported lidar, upgrade/APP implications,
   endpoint schemas, coordinate frames, units, command correlation, watchdogs,
   failure/cancel states and map/task persistence.
4. Ask Unitree for unresolved serial-specific safety/electrical limits listed
   in [the acceptance checklist](./acceptance-checklist.md).
5. Update this bundle's claim tables and dates together. Do not silently
   replace conflicting values or promote untested examples into safe limits.
