# Unknown limits and deployment acceptance

This is a documentation/engineering checklist, not a hardware test plan.
Do not discover safety limits by driving to failure or bypassing local guards.
An unpublished value remains unknown until confirmed for the installed revision.
The absence of a published constraint is not evidence that no constraint exists.

## Configuration record required before integration

- Exact model and hardware revision; mounted payload mass, mounting geometry,
  center of mass, arm swept volume and ground clearance.
- Firmware, remote/app, SDK2 commit/release, ROS message revision, ROS distribution,
  DDS configuration, interface and active motion-controller ownership.
- Navigation software/version/license; compute and sensor bill of materials;
  sensor extrinsics, time synchronization and calibration provenance.
- Map identity/version/coordinate frame, localization initialization procedure,
  route version, recovery policy, supervisory operator and physical stop access.

## Limits to obtain from Unitree or an approved integrator

| Unknown or conditional quantity | Evidence needed before relying on it |
|---|---|
| Stopping time/distance | Validated speed, payload, slope, surface, controller and failure-mode conditions |
| Motion watchdog behavior | Firmware-specific timeout, stale command handling, network-loss behavior and tested stop semantics |
| Payload center-of-mass/moment envelope | Mounting coordinate system, allowed static/dynamic moments and arm configurations |
| Combined performance | Approved combinations of load, slope, speed, gait, temperature and terrain |
| Joint/control constraints | Per-joint position, velocity, torque/current, thermal derating, rate limits and approved control modes |
| Support polygon/stability | Validated dynamic stability/rollover margins for the installed payload |
| Environmental operation | Temperature/humidity/altitude, ingress test conditions, wet connector/charging restrictions |
| Battery behavior | Usable energy, reserve, low-voltage stop policy, aging, charge temperature and replacement procedure |
| Interfaces/power budget | Connector pinout, voltage tolerances, startup surge, current limit, fusing and grounding |
| Navigation safety envelope | Minimum obstacle size, blind zones, dynamic obstacle limits, overhang/drop-off handling and terrain exclusions |
| Localization failure | Quality thresholds, detection latency, lost-localization stop behavior and supported reinitialization |
| Navigation command semantics | Protocol/message version, units, acknowledgement versus completion, cancellation and restart behavior |
| Map/route persistence | Format/version, file locations, naming/overwrite rules and restart persistence |
| Network/compute load | QoS, supported rates, packet loss/latency envelope and overloaded-process behavior |
| Emergency stop | Physical/remote/software distinction, scope, reaction, reset and any actual safety certification |

Do not mark every entry "unknown to Unitree": some may exist in delivery-specific
manuals. Distinguish **not found in the public sources read**, **documented but
not validated on this installation**, and **not applicable**.

## Acceptance gates

1. **Documentation gate:** a primary source and version exist for each interface
   being implemented; unresolved safety-critical ambiguities are escalated.
2. **Compatibility gate:** installed hardware/firmware/software match those
   documents; Go2, B2-W and SDK examples have not been silently substituted.
3. **Ownership gate:** only the intended controller can command locomotion.
   Navigation and teleoperation do not race.
4. **Read-only gate:** state freshness, faults, power, temperature, sensor
   timestamps, frame transforms and map/localization identity are established.
5. **Safety gate:** an approved site-specific procedure, exclusion zone, trained
   operator and physical stop are available. This skill alone does not authorize
   movement or certify autonomous operation.
6. **Integration gate:** missing local wrapper features are implemented through
   the project's approved engineering process, not ad-hoc ROS/SDK bypasses.
7. **Validation gate:** subsequent tests use an approved staged plan and record
   actual outputs. A successful API acknowledgement is not successful motion,
   localization, mapping, route completion or safe stopping.

## Answer format for an undocumented limit

> I could not verify [quantity] in [specific sources/revisions inspected].
> The published [related rating] does not establish this limit. For this robot,
> obtain [specific revision-dependent evidence] from Unitree/integrator.
> Until then, [retain existing guard / do not enable the affected feature].

Avoid "probably", synthetic vendor values and apparently precise estimates
without conditions and an explicit inference label.
