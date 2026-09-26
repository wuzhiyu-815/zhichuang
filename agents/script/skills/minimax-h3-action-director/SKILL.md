---
name: minimax-h3-action-director
description: Create professional MiniMax H3 action scene prompts using martial arts choreography, director style integration, high-speed cinematography techniques, and precision timing. Input: action style + director reference + scene type + duration. Output: optimized H3 prompt + shot breakdown + camera strategy + sound design. Supports 14 director styles × 7 martial arts types × 45+ camera techniques × 8 scene templates.
---

# MiniMax H3 Action Director Skill

Generate professional, frame-accurate MiniMax H3 (Hailuo 3.0) prompts for high-speed action scenes. This skill integrates cinematic direction (Sofia Coppola, Kathryn Bigelow, Park Chan-wook, etc.) with authentic martial arts choreography (Hong Kong kung fu, Brazilian jiu-jitsu, boxing, etc.) and high-speed cinematography techniques to produce action sequences that are both visually clear and narratively powerful.

**What makes this different:** Most action prompts are generic. This skill plans before writing—it analyzes your action style, director aesthetic, and scene structure, then produces a frame-accurate timing chart and optimized H3 prompt that actually delivers control over camera movement, impact moments, and pacing.

## Quick Start: Four Modes

### Mode 1: Quick Mode (2 min)
**Input:** "Create a 10s one-on-one fight, Sofia Coppola style, warehouse, slow-motion at impact"

**Process:** 
- Match director + martial art
- Apply 3-shot template (approach, exchange, impact)
- Generate single optimized prompt

**Output:** Prompt ready to paste

---

### Mode 2: Detailed Mode (5-10 min)
**Input:** Full JSON with action_type, duration, director_style, scene_type, environment, camera_mood, special_requirements

**Process:**
1. Validate against director integration matrix
2. Build 0.1-second timing chart
3. Apply high-speed cinematography rules
4. Generate prompt + shot breakdown + audio design

**Output:** Complete prompt + timing chart + cinematography analysis

---

### Mode 3: Template Mode (3 min)
**Input:** "Use 'one-on-one-duel' template, adapt for park noir, 8 seconds, Bigelow style"

**Process:**
- Load template shot sequence
- Customize for director/environment
- Generate adapted prompt

**Output:** Prompt + scene structure

---

### Mode 4: Director Study Mode (5 min)
**Input:** "How would Sofia Coppola shoot a 10s Muay Thai fight?"

**Process:**
- Consult director style database
- Analyze martial art characteristics
- Show integrated prompt + visual strategy

**Output:** Full analysis + reference prompt

---

## The Core Workflow

### Step 1: Gather Input
```
Required:
- action_type: hongkong_kung_fu | brazilian_jitsu | boxing | muay_thai | 
              sword_fighting | kickboxing | wrestling | karate
- duration: 5-15 seconds (target 8-12s)
- director_style: [name or two-part blend]
- scene_type: one_on_one_duel | multi_opponent | pursuit | defense_counter |
              staircase_hallway | environmental | weapon_duel | desperation_final
- environment: warehouse | rooftop | rain | corridor | forest | arena | confined_space

Optional:
- camera_mood: intimate_tense | documentary_verite | balletic_choreographed | 
               explosive_kinetic | clinical_precision | dreamlike_surreal
- special_requirements: slow_motion_impact | weapon_emphasis | environmental_use |
                       handheld_tension | sound_design_heavy
```

### Step 2: Validate Director-Martial Art Fit
Use `references/director_integration_matrix.md` to check:
- Does this director style match this martial art?
- What visual/pacing adjustments are needed?
- Which camera techniques are most effective?

### Step 3: Build 0.1-Second Timing Chart
Create frame-accurate timeline:
- **Column 1 (Time):** 0.0s → target duration, 0.1s increments
- **Column 2 (Camera):** state, motion type, position changes
- **Column 3 (Action):** choreography, fighter position, expression
- **Column 4 (Audio):** impacts, breathing, ambient, music events

Example row:
```
| Time  | Camera State | Fighter Action | Audio Event |
| 2.3s  | Hold static close-up on face | Eyes widen as punch connects | "Thud" impact at 3kHz |
```

**Key budgeting rules:**
- Held beats (no camera motion): minimum 2.5s
- Slow push-in: 3-6s typical
- Fast camera move: 0.3-1.0s max
- Strike exchange: 0.6-1.2s per shot
- Impact + recovery: 0.2-0.5s

### Step 4: Apply Cinematography Rules
For each shot, apply high-speed action principles:
- **Running speed faster than clarity allows?** → Use slow push-in to compensate
- **Need to show impact detail?** → Hold static frame 0.2-0.3s
- **Multiple rapid strikes?** → Arc tracking at 40-60% of strike speed
- **Handheld verité effect?** → Micro-camera wobble (±2 pixels), never smooth
- **Director wants painterly?** → Slow lateral tracking, wide depth of field, soft foreground

### Step 5: Generate Prompt
Convert timing chart into H3 syntax:
- Group shots at true cuts only (use `[Shot N]` blocks)
- Write camera motion as natural prose using official vocabulary
- Every action as observable behavior (not emotion)
- Timestamp every cut to 0.1s precision
- Fill integrated_multimodal_description, overall_soundscape, non_diegetic_music

### Step 6: Certify
Run through checklist:
- ✓ Task type and reference mode correct?
- ✓ Static shots forbid drift (not just "static")?
- ✓ All actions as observable behavior?
- ✓ Timing chart sums to target duration?
- ✓ Highest-priority beat not in last 10%?

---

## Integration Points with Reference Materials

### 1. Director Styles (`references/director_styles.md`)
14 directors with documented visual grammars:
- Sofia Coppola (pastel, static, contemplative)
- Kathryn Bigelow (handheld, tension, documentary)
- Park Chan-wook (geometric, saturated, baroque)
- Denis Villeneuve (precision, wide landscape, tense)
- Chloé Zhao (verite, natural light, humanist)
- Lynne Ramsay (fractured, textural, subjective)
- Greta Gerwig (whimsical, choreographed, musical)
- Jane Campion (sensual, sensory, proprioceptive)
- Andrea Arnold (intimate, folk-textured, sensory)
- CEline Sciamma (architectural, political, careful)
- Lee Chang-dong (patient, painterly, poetic)
- Pedro Almodóvar (maximalist, color-driven, emotional)
- Bong Joon-ho (tonal shift, structure, genre-blend)
- Claire Denis (durational, abstract, embodied)

### 2. Martial Arts Action (`references/martial_arts_action.md`)
7 core types with choreography profiles:
- **Hong Kong Kung Fu:** Fast cutting, close-ups on contact, prop use
- **Brazilian Jiu-Jitsu:** Slow, ground-based, intimate distance, leverage emphasis
- **Boxing:** Stance-based, head movement, rapid exchanges, torso control
- **Muay Thai:** Rotational power, clinch positioning, eight-point strike system
- **Sword Fighting:** Line-based geometry, extension emphasis, point-to-point clarity
- **Kickboxing:** Hybrid stance, leg-heavy, rotational, distance control
- **Professional Wrestling:** Dramatic positioning, partner coordination, impact exaggeration

### 3. High-Speed Cinematography (`references/high_speed_cinematography.md`)
Classic film techniques that work with AI models:
- Slow push-in as clarity compensation (black Kurosawa technique)
- Static/hold frames at impact (Lee technique)
- Arc tracking to reduce relative motion (Chan technique)
- Strategic cutting to hide blur (Bigelow technique)
- Visual focus design (high contrast, foreground isolation, background simplification)

### 4. Quick Reference (`references/quick_reference.json`)
- All 7 martial art keywords and variations
- Director speed-lookup table
- 45+ camera technique vocabulary
- Audio design templates
- Best practices checklist

---

## Output Format

### 1. Mode Line
State: task type, duration, director style(s), why chosen.

### 2. Timing Chart (Markdown Table)
Shows every discrete change, timestamped to 0.1s, with camera/action/audio columns.
This is the artifact that proves your timing works before spending a generation.

### 3. Final Prompt (Fenced Code Block)
Exact MiniMax H3 syntax, ready to paste:
```
Task type: T2VA (or I2VA/FL2VA/L2VA as applicable)
Duration: 8 seconds
[Shot 1] At 0.0s, ...
[Shot 2] At 2.3s, ...
[Shot N] At [time], ...
integrated_multimodal_description: [prose]
overall_soundscape: [prose]
non_diegetic_music: [prose]
```

### 4. Certification Note
One or two lines confirming the load-bearing checks for this prompt.

---

## Trigger Keywords

Use this skill when the user asks:
- "Create an action scene prompt" / "Action scene MiniMax"
- "动作指导" / "编排打斗" / "生成动作场景"
- "Action director" / "Choreograph fight" / "Fight scene storyboard"
- "Design a [martial art] fight, [director] style"
- "10s action scene with..." (any mention of action + style + duration)
- "How would [director] shoot a [martial art] fight?"
- "I need a prompt for a punch-up / sword duel / fight sequence"

**Always trigger for:** Any request combining action, choreography, director name, and video generation.

---

## Key Principles

### Principle 1: Plan Before Writing
Vague action prompts produce generic results. Build the timing chart first. Show it to the user. Make sure it adds up. Only then write the prose.

### Principle 2: Observable Behavior, Not Emotion
Write: "Fist impacts chin with full force visible in head snap"
Don't write: "Devastating punch that shows the fighter's anger"

### Principle 3: Director Style Shapes Everything
- Coppola → longer holds, wider shots, pastel mood
- Bigelow → handheld, tight close-ups, tension rhythm
- Park → saturated colors, geometric framing, baroque motion
- Choose deliberately; don't default to neutral.

### Principle 4: Martial Art Dictates Pacing
- Boxing: Quick exchanges, 0.6-1.0s per shot
- BJJ: Slow, 2-4s per position change, intimate framing
- HK Kung Fu: Rapid cutting, 0.3-0.8s per strike, wide shots interspersed
- Sword: Line-based, geometric, 1.5-3s per engagement

### Principle 5: High-Speed Motion Needs Strategy
Motion blur in AI is like motion blur in pre-digital film: you can't fight it directly. Instead:
- Use slow push-in to create psychological clarity
- Hold static at impacts to "confirm" the action
- Use arc tracking to reduce relative motion
- Strategic cutting to hide blur at maximum speed
- Audio/editing psychology to sell the clarity

---

## When to Adjust the Template

If the timing chart doesn't fit your duration:
- Cut a beat entirely (not recommend—reconsider scope)
- Extend holds (recommend: increases tension)
- Reduce strike exchanges (cut one round from the combo)
- Speed up non-action transitions (camera moves, repositioning)

**Never:** Compress impact moments or hold frames. These are the payoff.

---

## Example: One-on-One Duel (10s, Sofia Coppola, Warehouse)

**Mode:** Detailed

**Input:**
```json
{
  "action_type": "hongkong_kung_fu",
  "duration": 10,
  "director_style": "Sofia Coppola",
  "scene_type": "one_on_one_duel",
  "environment": "warehouse_shadows",
  "camera_mood": "intimate_tense",
  "special_requirements": "slow_motion_at_impact"
}
```

**Timing Chart:**
```
| Time | Camera State | Fighter Action | Audio |
| 0.0-1.5s | Static wide, soft focus bg | Both fighters in ready stance, breathing sync | Warehouse ambient, distant drip |
| 1.5-2.0s | Slow push-in (1m) | Fighter A circles, eyes tracking | Footsteps, breathing quickens |
| 2.0-2.8s | Hold close-up, fighter A | A throws 3-strike combo, B defends | Impacts: thud-block-thud |
| 2.8-3.5s | Slow arc left | B counters with kick, A rolls back | Kick whistle, exhale, gap sound |
| 3.5-4.2s | Hold on impact | Kick connects; 0.3s hold shows force in body | Impact thud, pain grunt |
| 4.2-6.0s | Static on A's face | A recovers stance, B reset; breathing hard | Labored breathing sync, ambient |
| 6.0-8.0s | Slow push-in (2m) | Final exchange: A leads, B defends-counter, A blocks | 5 rapid impacts, building intensity |
| 8.0-8.3s | Impact hold | B's strike connects A's forearm; both tense | Maximum impact thud |
| 8.3-10.0s | Pull back slow arc | Both reset, circling, eye contact, defiant stance | Breathing sync, single low cello note |
```

**Final Prompt:**
```
Task type: T2VA
Duration: 10 seconds

[Shot 1] At 0.0s, the camera is positioned wide and static 12 meters from two martial artists facing off in a warehouse. Soft shadows from high windows. Both fighters are in ready stance, breathing in sync, eyes locked. Background is deep, out-of-focus shipping containers. Lighting: 60-degree side light creates dramatic shadow lines without harsh contrast. Color palette: Desaturated with slight warm (amber) tint. No camera motion.

[Shot 2] At 1.5s, the camera slowly pushes in toward the fighters over 0.5 seconds, moving from 12 meters to 11 meters at constant, glacial speed. Composition remains centered. Fighter A begins to circle slightly (small steps, weight-balanced). B tracks A's eyes. Soft exhales, warehouse ambience with single distant water drip.

[Shot 3] At 2.0s, camera holds close-up on Fighter A's upper body (waist to top of head). Fighter A delivers rapid 3-strike combination (punch-palm-punch), each at full speed. Fighter B's arms rise in sequential blocks, visible muscular tension in forearms. Facial expressions: A concentrated, B focused on defense.

[Shot 4] At 2.8s, camera executes slow arc tracking left (40% of B's movement speed), maintaining B's position in frame center. B pivots and launches a spinning back kick toward A. The kick motion shows 45% directional blur; leg trajectory is unambiguous. A sees the kick, begins roll evasion.

[Shot 5] At 3.5s, camera returns to static hold on impact moment (0.3 seconds hold). B's kick meets A's forearm block. Extreme force visible: A's arm compresses slightly, body absorbs impact, face shows pain grimace, eyes wince. The 0.3-second hold lets audience process the impact. Audio: Clean kick-block impact thud at 2.5kHz frequency with subsonic bass component.

[Shot 6] At 4.2s, camera pulls back to static medium shot on A's face and upper body (4 meters distant). A recovers from the block, drops stance, resets to ready position. Breathing is deep and labored, visible chest heave. B mirrors the stance reset across the frame. Eyes remain locked, defiant. Warehouse ambient sound only, overlapped with synchronized breathing from both fighters.

[Shot 7] At 6.0s, camera begins slow push-in (2 meters over 2 seconds). Fighters close distance slightly with footsteps. A leads with a test jab. B parries. A continues with straight punch. B slips left and counters with palm strike toward A's ribs. A pivots block. Four rapid impacts over 2 seconds. Muscular definition visible in arms and shoulders during each movement.

[Shot 8] At 8.0s, camera returns to static impact hold. B's final counter-strike (palm heel) meets A's defensive cross-arm block. Force transmission visible through A's entire body: shoulders rise, feet brace into ground, face tightens with effort. Eyes and jaw muscles show strain. Hold this frame for 0.3 seconds to register maximum tension.

[Shot 9] At 8.3s, camera executes slow arc pull-back (3 meters over 1.7 seconds) to medium wide shot. Both fighters reset to ready stance, breathing heavily, chests heaving. Small steps as they circle, maintaining distance. Eye contact unbroken. No contact, only positioning. Final 1-second hold as stance reaches equilibrium.

integrated_multimodal_description: One-on-one martial arts duel in warehouse, Sofia Coppola aesthetic with pastel-tinted desaturation, intimate framing despite violence, slow camera motion emphasizing contemplation over action, impacts held to register maximum tension, breathing and eye contact as primary emotion drivers.

overall_soundscape: Layer 1 (ambient): Warehouse drone, distant water drips, minimal reverb. Layer 2 (impact): Clean, dry punch/block sounds at 2-4kHz, no artificial reverb, every contact distinct. Layer 3 (body sounds): Breathing synchronized between fighters, audible footsteps on concrete, fabric rustles with rotation. Layer 4 (emotional): Subtle low cello note enters at 8.3s, held to end, emphasizing tension without melodrama.

non_diegetic_music: Single cello note (C2) enters at 8.3s and extends through 10.0s at barely audible volume (10% of impact sounds). The note is held, not bowed, creating a tone of stillness despite physical exertion. No percussion, no melody, only sustained tension.
```

**Certification:**
✓ Timing chart sums to exactly 10.0s
✓ Impact holds at 2x optimal duration (0.3s each) for Coppola's contemplative style
✓ High-priority beat (final strike) positioned at 8.0-8.3s, outside the last-10% compression zone
✓ All action described as observable behavior (body tension, muscle strain, eye contact, breathing pattern)
✓ Camera motion paced to 40-60% of action speed to maintain perceived clarity
