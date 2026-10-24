# Research Report: ENPIRE—Agentic Robot Policy Self-Improvement in the Real World

**Paper:** [ENPIRE: Agentic Robot Policy Self-Improvement in the Real World](https://arxiv.org/abs/2606.19980)  
**Authors:** Wenli Xiao, Jia Xie, Tonghe Zhang, and collaborators from NVIDIA, Carnegie Mellon University, and UC Berkeley  
**Version reviewed:** arXiv v2, revised September 20, 2026; listed as a 2026 Conference on Robot Learning paper  
**Project and code:** [Project page](https://research.nvidia.com/labs/gear/enpire/) · [GitHub repository](https://github.com/NVlabs/ENPIRE)  
**Code license:** Apache-2.0

## Executive summary

ENPIRE is a framework for coding agents to improve robot policies through repeated experiments on physical robots. Its central idea is to make the real-world learning loop repeatable: reset the task scene, run a policy, automatically verify the outcome, record evidence, and use that evidence to decide what to try next.

The work’s primary contribution is **the infrastructure for agent-driven physical experimentation**, rather than a new policy-learning algorithm. The authors demonstrate agents exploring heuristics, behavior cloning, and reinforcement learning on several manipulation tasks. They also show that adding robot-agent pairs can reduce the time to reach a target performance—though it increases token consumption and does not keep every robot fully utilized.

The headline success figures require care: the project page’s reported **99% pass@8** is not a one-attempt success rate. It allows up to eight adaptive attempts, with retries conditioned on previous failures.

## Research problem

Real-world robot learning typically requires people to manage data collection, reset the scene, evaluate outcomes, diagnose failures, and tune algorithms. Those steps make autonomous improvement difficult, even when coding agents can already modify and test algorithms in digital environments.

ENPIRE asks whether a coding agent can make progress directly on real hardware if given an interface that supports safe, repeatable experimentation. The authors identify three key requirements:

- **Reset:** return the physical scene to a valid starting state.
- **Verification:** determine whether the task succeeded without human judgment on every trial.
- **Experimentation:** let agents execute policies, inspect evidence, and update the policy or training code.

## System design

The paper describes a two-stage process and a four-part framework.

### Stage 1: Construct the environment interface

With human feedback, coding agents help create task-specific interfaces for:

- **Safety:** constrain robot motion and terminate unsafe or invalid trials.
- **Automated verification:** score success from camera images, robot state, and—in some cases—force estimates.
- **Automated reset:** return the scene to a suitable starting configuration for the next trial.

Once validated, these interfaces are treated as fixed APIs for the policy-improvement phase.

### Stage 2: Improve the policy

Agents use the environment APIs to conduct experiments. They can inspect logs, videos, trajectories, and reward signals; review relevant literature; and change policy or training code.

The framework’s modules are:

| Module | Role |
|---|---|
| **EN — Environment** | Reset, safety, and verification interfaces |
| **PI — Policy Improvement** | Policy and training-code changes |
| **R — Rollout** | Run and record experiments on one or more robots |
| **E — Evolution** | Compare, share, retain, or abandon research ideas |

For multi-robot runs, agents operate asynchronously on separate stations and share code and findings through Git.

## Experimental setup and tasks

The paper evaluates physical autoresearch on four manipulation tasks:

- **Push-T:** push a T-shaped object into a target pose.
- **Pin insertion:** insert pins into 4 mm diameter holes.
- **GPU insertion:** seat a GPU into a motherboard slot.
- **Zip-tie manipulation:** manipulate a zip tie and cut its tail.

The physical platform is a fleet of up to eight bimanual YAM robot stations. The paper reports a 30 Hz policy loop and station-local compute, including an RTX 5090 GPU per station.

Agents are allowed to explore multiple learning approaches, including heuristic or code-based policies, behavior cloning, and online or offline reinforcement learning. The paper compares Codex with GPT-5.5, Claude Code with Opus 4.7, and Kimi Code with Kimi K2.6 in selected experiments.

## Main results

### Policy improvement on physical tasks

The authors report that ENPIRE enables coding agents to improve policies across the showcased physical tasks. The project page reports **99% pass@8** across the demonstrated tasks.

That metric is important to interpret correctly:

- It is **not** the probability that a single attempt succeeds.
- It permits up to eight retries within a rollout.
- Retries can be informed by prior failures, so the measure includes recovery behavior as well as initial execution accuracy.

For pin insertion, agents tested behavior cloning, online data aggregation, and combinations of RL with behavior-cloning regularization. The paper’s experiment tree identifies BC regularization as a particularly useful improvement, followed by smaller refinements such as batch-size and controller adjustments.

### Scaling across robot fleets

The authors compare teams of one, four, and eight robot-agent pairs. They report that larger teams reach target performance sooner:

- **Push-T:** roughly five hours with one agent versus about two hours with eight.
- **Pin insertion:** over 1.5 hours with one agent versus roughly 40 minutes with eight.

These are reported wall-clock times for the authors’ experimental setup, not general guarantees for other robots or tasks.

### Simulation results

The paper also evaluates agentic manipulation in RoboCasa simulation, including combinations of learned policies with perception and motion-planning tools. It reports advantages over selected comparison approaches in that setting. These simulation results complement the physical experiments but should be distinguished from evidence of real-world generalization.

### Resource use

The authors introduce **Mean Robot Utilization (MRU)** and **Mean Token Utilization (MTU)** to characterize resource use during autoresearch.

They report two scaling costs:

- Robot utilization per station drops as the number of agents increases, partly because agents spend time analyzing results, editing code, and coordinating.
- Token consumption grows faster than the ideal linear projection at larger fleet sizes.

In short, larger fleets can reduce elapsed time, but the speedup comes with greater resource cost and coordination overhead.

## Strengths

1. **Targets a real bottleneck.** The work addresses the labor involved in repeatedly resetting, evaluating, and adjusting physical robot experiments.
2. **Builds around measurable feedback.** Automated verification makes experiments easier to compare and less dependent on human judgment at each trial.
3. **Supports different improvement methods.** The framework is not tied to one optimizer; agents can explore heuristics, imitation learning, and RL.
4. **Tests on real hardware.** Physical trials expose variation in contact, friction, and dynamics that simulation may not capture.
5. **Makes the framework available.** The [public repository](https://github.com/NVlabs/ENPIRE) is licensed under Apache-2.0 and includes documentation and examples.

## Limitations and qualifications

- **Environment construction still requires human input.** Task setup, safety boundaries, reset behavior, and verification must be defined and validated. The autonomy claim applies most strongly after those interfaces are in place.
- **The interfaces are task-specific.** Reset and reward functions that work for pin insertion may not transfer directly to another task.
- **Headline success includes adaptive retries.** Pass@8 should not be compared directly to one-shot success rates.
- **Results are task- and setup-dependent.** The paper notes that real-world Push-T is substantially harder than simulation; two of the three evaluated agents failed on the physical task in the reported comparison.
- **Fleet scaling has diminishing efficiency.** More agents can accelerate progress, but utilization falls and token costs rise.
- **The evaluation scope is limited.** Four showcased physical manipulation tasks and a particular robot platform do not establish broad, general-purpose robotic competence.

## Assessment

ENPIRE’s strongest contribution is a practical blueprint for turning physical robot learning into an agent-operable experiment loop. It demonstrates that coding agents can use structured real-world feedback to search over policy and training changes, and that parallel physical experiments can shorten time to a result.

The work does **not** show that agents can independently invent robust environments, solve arbitrary manipulation tasks, or achieve 99% first-attempt reliability. Instead, it shows that once people provide a carefully constructed environment—with safe controls, reset procedures, and trustworthy verification—agents can automate a meaningful portion of the subsequent policy-improvement process.

## Sources

- [ENPIRE project page](https://research.nvidia.com/labs/gear/enpire/)
- [Paper: arXiv:2606.19980](https://arxiv.org/abs/2606.19980)
- [ENPIRE source repository](https://github.com/NVlabs/ENPIRE)
