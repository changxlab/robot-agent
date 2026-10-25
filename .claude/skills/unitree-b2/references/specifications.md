# B2 specifications and interpretation

Research checked 2026-10-25. Source identifiers and revision dates are in
[the source register](./sources.md). These are published manufacturer claims,
not measured performance of this arm-equipped installation. Preserve the
inequalities: ">40 kg" is not an independently established safe payload limit.

## Physical and performance parameters

Unless stated otherwise, values below are from the official B2 product page
[S1](https://www.unitree.com/b2), corroborated where available by
[S2, About B2](https://support.unitree.com/home/en/B2_developer/About%20B2).
Conditions for simultaneous operation at multiple maxima are not published
in the material read.

| Parameter | Published value | Interpretation |
|---|---|---|
| Standing dimensions, L x W x H | Approximately 1098 x 450 x 645 mm | Bare-body nominal dimensions, not payload swept volume |
| Prone/folded dimensions | Approximately 880 x 460 x 330 mm | Not standing ground clearance |
| Mass, including battery | Approximately 60 kg | Excludes this deployment's arm and other payloads |
| Degrees of freedom | 12 (S2) | Four legs, three joints each |
| Standing load | >=120 kg (S1) | Static rating, not walking or mounting-moment limit |
| Walking load | >40 kg (S1) | No full center-of-mass/dynamic load envelope supplied |
| General operating time | 4-6 h | Published operating-time figure, not guaranteed autonomy |
| Unloaded continuous walking | >5 h; >20 km (S1) | No complete terrain/speed/weather test method supplied |
| Continuous walking with 20 kg | >4 h; >15 km (S1) | Not the same condition as maximum walking payload |
| Running speed | >6 m/s | Special configuration; vendor states actual speed is safety-limited |
| Joint torque headline | Approximately 360 N m (S1) | Peak/continuous duty distinction and per-joint envelope not established |
| Continuous stair rise | 20-25 cm | Do not equate to 40 cm continuous stairs |
| Forward step/stair climbing claim | 40 cm (S1) | Separate from the continuous-stair specification; scenario-dependent |
| Slope capability | >45 degrees | Bare hardware claim, not autonomous navigation's ramp envelope |
| Ditch jumping width | 0.5-1.2 m | Not clearance for autonomous walking |
| Maximum jump distance | >1.6 m | No safe jump workflow for this arm-equipped robot |
| Operating temperature | -20 to 55 C | S2 qualifies operation as under good weather conditions |
| Ingress protection | IP67 | Does not establish whole-payload protection or charging conditions |

No jumping, high-speed operation or deliberate operation at maxima is authorized
by this skill.

## Battery: a source discrepancy that must not be hidden

| Item | Product page S1 | Developer page S2 |
|---|---|---|
| Capacity | 45 Ah / 2250 Wh | 45 Ah / 2268 Wh |
| Voltage | 58 V, without the same nominal/charge distinction | Standard 50.4 V; charging 58.8 V |
| Model | Not in extracted table | BT2-10 |
| Battery mass | Not in extracted table | 12.2 kg |
| Charging current | Not in extracted table | 10 A |
| Charging time | Not in extracted table | 3 h 20 min |

Report both sources and the mismatch. **Do not choose 58 V as the nominal pack
voltage or substitute 58.8 V for it without explanation.** The developer table's
50.4 V x 45 Ah equals 2268 Wh, but arithmetic consistency alone does not resolve
product revision or charger compatibility. Verify the actual battery and charger
labels and revision-specific manual before any electrical work.

## Compute, perception and expansion

S1/S2 list:

- Standard compute: Intel Core i5 for platform functions and Core i7 for user
  development. Optional compute includes Core i7 and NVIDIA Jetson Orin NX;
  the pages describe configurations up to three devices. Exact installed
  processors, memory, GPU and power budget require inventory.
- Sensor configuration: one 3D lidar, two depth cameras and two optical cameras;
  configuration varies. S2 describes front/rear camera placement. Do not assume
  optional robot payload cameras replace or match this factory configuration.
- External interface counts: four 1000M-Base Ethernet, four USB 3.0, four 12 V,
  one 5 V, four 24 V and one BAT interface. These counts do not define per-port
  electrical budgets.
- Quick battery replacement and optional autonomous charging are advertised;
  neither establishes hot-swap capability or a supported local docking command.

### Electrical budgets: S2, "Electrical Interfaces"

| Circuit | Published limits | Sharing/qualification |
|---|---|---|
| USB TYPE-C | 3 A aggregate; 1.5 A per port | Shared with the abdominal processor TYPE-C supply |
| 24 V output | 10 A total rated; 15 A slow-blow one-time fuse | All 24 V interfaces share a parallel supply; no independent per-port allocation |
| 24 V overcurrent protection | Triggers at 24 A, resets at 16 A | Hiccup self-recovery; not permission to exceed 10 A rating |
| 12 V network/power output | 10 A total rated; 15 A slow-blow one-time fuse | Shared with abdominal processor; table describes overall internal power parameters |
| 12 V overcurrent protection | Triggers at 24 A, resets at 16 A | Parallel shared supply; available accessory budget is not the full internal rating |

**Aviation connector hot-plugging is explicitly prohibited by S2.**
Connector pinouts and mechanical drawings must be read from the current official
page for the exact connector orientation/revision. Do not infer mating-face
orientation from wire colors or turn aggregate ratings into per-port ratings.
The BAT and 5 V entries lack a verified usable accessory-current limit here.
Do not supply one by extrapolation.

## Joint indexing and limits: S2

Leg order: 0 FR, 1 FL, 2 RR, 3 RL. Joint order within a leg: 0 hip/trunk,
1 thigh, 2 calf. S2 describes hip rotation about x and thigh/calf about y,
using the right-hand rule.

| Joint | Numeric bounds as printed in S2 |
|---|---|
| Hip/trunk | -0.87 to 0.87 |
| Thigh | -0.94 to 4.69 |
| Calf | -2.82 to -0.43 |

**Unit caveat:** the retrieved joint-limit lines do not explicitly label their
units. They are consistent with conventional radian joint limits, but do not
issue commands or conversions on that inference alone. Confirm against the
matching URDF and revision-specific control manual. The zero-pose illustration
is not a physically attainable calf pose.

Joint position limits do not provide velocity, current, torque, thermal,
controller-frequency or allowed contact-force limits. The 360 N m headline is
not a low-level torque command envelope.

## Different envelopes, not contradictory commands

| Layer | Published/current constraint |
|---|---|
| Bare B2 locomotion headline | >6 m/s in special configuration, safety-limited in actual operation |
| Optional industry navigation, legged | 0.1-1 m/s; ramps <=30 degrees; stairs <=45 degrees (S5) |
| This robot-agent wrapper | Component bounds 0.5 m/s forward, 0.3 m/s lateral, 0.6 rad/s yaw; at most 3 s per move |

Do not label the product speed as ordinary teleoperation speed: the source
does not establish that. Do not increase local limits to match the navigation
software's advertised range. The minimum of applicable validated constraints
governs, together with payload/site restrictions.
