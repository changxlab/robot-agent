---
name: b2-locomotion
description: Read state of and command the Unitree B2 quadruped base - stand up, lie down, balance stand, walk with bounded velocity, stop, damp. Use for any request to move, walk, turn, stand or sit the robot body, or to stop it.
---

# Unitree B2 base

```bash
./robot base state                                 # read-only: mode, battery, faults, pose
./robot base stand-up
./robot base balance-stand                         # required before walking on some firmware
./robot base move --vx 0.3 --duration 2            # forward 0.3 m/s for 2 s, then stop
./robot base move --vyaw 0.4 --duration 2          # turn left in place
./robot base move --vx 0.2 --vy -0.1 --duration 1  # forward and to the right
./robot base stop                                  # stop walking (always allowed)
./robot base stand-down                            # lie down
./robot base damp                                  # all joints limp - the robot collapses
```

Units: `--vx`/`--vy` m/s (x forward, y left), `--vyaw` rad/s (positive = turn left), `--duration` s.
The tool clamps to `base.max_*` in `robot.yaml` (default 0.5 m/s, 0.3 m/s, 0.6 rad/s, 3 s) and always
sends stop-move at the end, so one command is one short, bounded motion. It refuses to walk when the B2
reports a fault, low battery, hot or lost motors, or is lying down.

Commands go to `/api/sport/request` (unitree_api/msg/Request) with the B2 sport API ids
(Damp 1001, BalanceStand 1002, StopMove 1003, StandUp 1004, StandDown 1005, Move 1008).

**`recovery-stand` is disabled.** The recovery motion rolls the body over and pushes it up, which
can crush the Piper arm, cameras and other devices mounted on the B2. The tool refuses it and the
command is blocked (only `base.allow_recovery_stand: true` in `robot.yaml` re-enables it - never
change that yourself). If the robot has fallen: run `./robot estop`, report the state, and tell
the operator it needs a manual recovery (secure or remove the payload, then the B2 remote or by
hand). Do not try other commands (`stand-up`, `balance-stand`, `damp`) to get it up.

## Stopping a move

- A `move` lasts at most `base.max_duration` (3 s) and always ends with StopMove - also when it is
  interrupted or its process is terminated.
- **E-STOP** in the web UI (it runs `./robot estop` on the server), `./robot estop` or
  `./robot base stop` interrupt a running `move` within about 0.1 s: the move stops sending
  velocity commands and sends StopMove. The move then fails with "interrupted by a stop request".
  These stop commands never need approval - use them immediately when anything looks wrong.
- The UI E-STOP is software over the network. The B2 remote controller / hardware emergency stop
  is the primary stop; the operator should keep it at hand during any motion.
- After a stop, check `./robot base state` and do not resume moving until the operator says so.

## Safety rules

1. The B2 is a large, heavy robot. Every motion command needs operator approval, which the UI requests
   when you issue the command. Say what the robot will do (direction, distance ~ speed x duration),
   then issue it - do not ask in chat or stop to wait.
2. Check `./robot base state` first; report and stop on a non-zero error code, low battery or motor issues.
3. Look through `b2_front` before walking forward (`b2_back` before walking backwards) to check the
   path is clear (`robot-camera` skill), and check `obstacle range` in the state output.
4. Prefer several short moves over one long move; re-check state between moves.
5. Do not send `damp` unless the operator explicitly asks - the robot will collapse. Before
   `stand-down` or `damp`, check with `./robot arm status` that the arm is folded at rest, since the
   body drops to the ground with the arm and devices on it.
6. Never send `recovery-stand` (disabled, see above).
7. Never publish to `/api/sport/request`, `/cmd_vel*` or `/keyboard_ctl` with `ros2 topic pub`; it
   bypasses the limits (these commands are blocked).
8. Navigation (Nav2, localization-driven inspection, survey) runs on the same computer. `base move`
   refuses to walk while velocity commands are flowing on `/cmd_vel_nav`; ask the operator to stop
   that run instead of working around it. Do not start `infai_bringup`, `dog_inspection` or
   `dog_survey` launches unless the operator asks - they can drive the robot.
9. On any doubt, run `./robot base stop` (or `./robot estop` for everything).
