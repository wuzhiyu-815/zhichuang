# Installation: MiniMax H3 Action Director Skill

## System Requirements

- **Claude 3.5 Sonnet or later** (for complex reasoning)
- **Claude Code** (local agent mode) or **claude.ai** (web)
- **Familiarity with MiniMax H3 / Hailuo 3.0 API** (optional but helpful)

## Installation Steps

### Option 1: Local Installation (Claude Code)

1. **Locate your skills directory:**
   ```bash
   # On macOS/Linux:
   ~/.local/share/claude/skills/
   
   # On Windows:
   %APPDATA%\Claude\skills\
   ```

2. **Extract the skill:**
   - Download `minimax-h3-action-director.skill` (a zip archive)
   - Extract to the skills directory above
   - Directory structure should be:
     ```
     skills/
     └── minimax-h3-action-director/
         ├── SKILL.md
         ├── INSTALL.md (this file)
         └── references/
             ├── action_director_workflow.md
             ├── director_integration_matrix.md
             ├── action_scene_templates.md
             └── quick_reference.json
     ```

3. **Restart Claude Code:**
   ```bash
   claude code
   ```

4. **Verify installation:**
   - Type `/action-director` in a message or trigger the skill with keywords like:
     - "Create an action scene prompt"
     - "Action director"
     - "Design a 10-second fight scene"
   - The skill should respond with available modes

### Option 2: Web Installation (claude.ai)

1. **Log into claude.ai** and access the skills panel
2. **Upload the skill file** using "Add skill" → "Upload from file"
3. **Select** `minimax-h3-action-director.skill` (zip archive)
4. **Confirm** installation

### Option 3: Manual Directory Setup (If Zip Not Available)

1. Create directory:
   ```bash
   mkdir -p ~/.local/share/claude/skills/minimax-h3-action-director/references
   ```

2. Copy files:
   - Place `SKILL.md` in the root directory
   - Place reference files in `references/` subdirectory

3. Restart Claude Code

---

## First Use: Quick Start

### Trigger the Skill

Type any of these to activate the skill:

**English Triggers:**
```
"Create an action scene prompt for a 10s one-on-one fight, Sofia Coppola style"
"Action director mode: Design a 12-second multi-opponent sequence"
"Generate a MiniMax H3 prompt for a sword duel, Park Chan-wook style"
"How would Kathryn Bigelow shoot a 8-second kickboxing exchange?"
"Action scene storyboard for a warehouse duel"
```

**Chinese Triggers:**
```
"创建一个10秒的索菲亚·科波拉风格单人对决动作场景提示词"
"动作指导：设计一个12秒的多对手打斗序列"
"编排一个8秒的快速拳击交换，朴赞郱风格"
"生成动作场景分镜：室内走廊，两人打斗，10秒"
```

### Skill Response

The skill will:
1. Ask clarifying questions if needed (duration, martial art, director style, scene type)
2. Generate a **timing chart** (0.1s precision) showing camera, action, and audio
3. Provide the **final MiniMax H3 prompt** (ready to copy/paste)
4. Include **certification notes** (verification that prompt will work)

---

## Workflow Overview

The skill follows a 6-step workflow:

### Step 1: Input Gathering
You provide (or skill asks for):
- Action type (HK kung fu, BJJ, boxing, muay thai, sword, kickboxing, wrestling)
- Duration (5-15 seconds)
- Director style (Sofia Coppola, Kathryn Bigelow, Park Chan-wook, etc.)
- Scene type (one-on-one, multi-opponent, pursuit, defense/counter, environmental, weapon, desperation)
- Environment (warehouse, rooftop, rain, corridor, etc.)

### Step 2: Integration Matrix Lookup
Skill consults `director_integration_matrix.md` to:
- Confirm director-martial art compatibility
- Identify visual/pacing adjustments
- Select optimal camera techniques

### Step 3: Timing Chart Creation
Skill builds a frame-accurate table:
- Time blocks (0.1s precision)
- Camera state + motion
- Fighter action (choreography)
- Audio events (impacts, breathing, ambient)

### Step 4: Cinematography Rules Application
Skill applies high-speed compensation:
- Slow push-in (if action speed high)
- Static impact holds (0.2-0.3s minimum)
- Arc tracking (if lateral movement rapid)
- Handheld micro-wobble (if tension-focused)
- Strategic cutting (if multiple rapid exchanges)

### Step 5: Prompt Generation
Skill converts timing chart to MiniMax H3 syntax:
- Shot blocks `[Shot N]` at true cuts only
- Observable behavior (not emotion)
- 0.1s timestamp precision
- Camera motion as natural prose
- Integrated audio/music description

### Step 6: Certification
Skill verifies:
- ✓ Timing sums to target duration
- ✓ Climax beat outside final 10%
- ✓ Static shots forbid drift
- ✓ Actions are observable behavior
- ✓ Director style evident throughout

---

## Skill Modes

### Mode 1: Quick Mode (2 minutes)
**Best for:** Simple, straightforward requests  
**Input:** "10s one-on-one, Sofia Coppola, warehouse"  
**Output:** Single optimized prompt

### Mode 2: Detailed Mode (5-10 minutes)
**Best for:** Complex scenes with specific requirements  
**Input:** Full JSON with all parameters + special requirements  
**Output:** Prompt + timing chart + cinematography analysis

### Mode 3: Template Mode (3 minutes)
**Best for:** Using established scene patterns  
**Input:** "Use one-on-one-duel template, adapt for park, Bigelow style"  
**Output:** Prompt + scene structure

### Mode 4: Director Study Mode (5 minutes)
**Best for:** Learning how directors approach action  
**Input:** "How would Sofia Coppola shoot a 10s Brazilian Jiu-Jitsu sequence?"  
**Output:** Full analysis + reference prompt + visual strategy

---

## Using the Timing Chart

The skill outputs a **timing chart** (markdown table) before the final prompt. This chart:

**Shows:**
- Time blocks (0.1s precision)
- Camera state and motion
- Fighter action and choreography
- Audio events and emphasis

**Lets you:**
- Verify timing adds up to duration
- Spot bottlenecks or pacing issues
- Approve choreography before prompt generation
- Make adjustments before asking for rewrites

**Example:**
```
| Time | Camera State | Fighter A Action | Fighter B Action | Audio Event |
|------|--------------|------------------|------------------|-------------|
| 0.0-1.5s | Static wide, 12m | Ready stance | Ready stance | Warehouse ambient |
| 1.5-2.0s | Slow push-in (1m) | Circles, testing | Mirrors movement | Footsteps, breathing |
| 2.0-2.8s | Hold close A | 3-strike combo | Defensive blocks | Impact sounds (3x) |
```

---

## Output: The Final Prompt

**Format:** Ready-to-copy MiniMax H3 syntax  
**Structure:**
```
Task type: T2VA (or I2VA/FL2VA/L2VA)
Duration: X seconds

[Shot 1] At 0.0s, [camera and composition description]
[narrative description of action]
[audio layer description]

[Shot 2] At [time]s, [camera state]
[narrative description]
[audio layer]

... [continue for all shot blocks] ...

integrated_multimodal_description: [synthesis of visual mood, director style, action strategy]

overall_soundscape: [description of all audio layers]

non_diegetic_music: [description of music treatment]
```

**Key characteristics:**
- Under 2000 tokens (MiniMax H3 efficiency)
- Every shot timestamped to 0.1s precision
- All actions as observable behavior
- Camera motion described as natural prose
- Static shots explicitly forbid drift
- Audio layers integrated with visual narrative

---

## Integration with Reference Materials

The skill automatically integrates:

1. **Director Styles** (`directors_visual_style_database.md`)
   - 14 documented directors with visual grammars
   - Camera defaults, cutting rhythm, palette per director
   - Blending guidance for combined styles

2. **Martial Arts Database** (`martial_arts_action_database.md` + Part 2)
   - 7 core martial arts types
   - Choreography profiles, framing requirements, pacing defaults
   - Technical highlights for each style

3. **High-Speed Cinematography Guide** (`high_speed_action_cinematography_guide.md`)
   - Classic film techniques (Kurosawa, Lee, Chan, Bigelow)
   - Compensation strategies for motion blur
   - Psychological clarity principles

4. **Action Camera Optimization Prompts** (`action_camera_optimization_prompts.json`)
   - 45+ pre-tuned camera technique prompts
   - Establishing shots, action sequences, impact moments, transitions
   - Audio design templates

---

## Customization & Advanced Usage

### Blending Director Styles

Request a blend of two directors:
```
"Create a 10s fight scene with Sofia Coppola's contemplative style 
and Kathryn Bigelow's handheld tension. One-on-one duel, warehouse."
```

The skill will:
- Use Coppola for establishing/recovery (long holds, slow push)
- Use Bigelow for action (short cuts, handheld)
- Blend color and pacing accordingly

### Custom Martial Art Fusion

If your martial art isn't listed (e.g., Tai Chi, Capoeira, Muay Boran):
```
"Design a 10s Capoeira demonstration, Greta Gerwig style. 
Treat it like dance-choreography, color-saturated, playful but grounded."
```

The skill will extrapolate from similar styles (HK kung fu has choreography emphasis, Greta likes musical rhythm).

### Special Requirements

Add specific needs:
```
"10s sword duel, Park Chan-wook style, but I need:
- Slow-motion on every blade clash
- Red accent color on blood/steel
- Minimal dialogue, music only
- Outdoor setting with visible sky"
```

The skill will adapt timing, color palette, and audio strategy accordingly.

---

## Troubleshooting

### "Prompt is too long (>2000 tokens)"
**Solution:** Reduce duration or complexity
- Shorter scene (8s instead of 15s)
- Fewer shot transitions (combine shots)
- Simpler martial art (HK is simpler than detailed sword choreography)

### "Timing doesn't add up"
**Solution:** Ask the skill to rebuild the timing chart
- May have compressed certain beats
- Ask: "Can you show me the timing chart first, before the final prompt?"

### "Camera motion is unclear"
**Solution:** Request more specific prose
- Ask: "Use only camera vocabulary from quick_reference.json"
- Specify exact distances and speeds: "Push-in from 12m to 10m over 3 seconds"

### "Director style not evident"
**Solution:** Reinforce director choice
- Remind skill which director you chose
- Ask: "Make sure [director]'s characteristic [technique] is clear in every shot"
- Request color palette emphasis: "Sofia's pastel desaturation should dominate the palette"

### "Martial art feels generic"
**Solution:** Add technical detail
- Specify techniques: "Use shuai jiao footwork, not generic kung fu"
- Ask for martial art reference: "This should feel like Jackie Chan films, not Bruce Lee"
- Request authenticity check: "Verify this BJJ choreography is realistic for the time given"

---

## Tips for Best Results

1. **Start with Quick Mode** if you're new to the skill
2. **Always review the timing chart** before accepting the final prompt
3. **Specify director style explicitly** (don't default to neutral)
4. **Match martial art to director** (e.g., BJJ + Sofia Coppola is natural; HK + Denis Villeneuve is harder)
5. **Use "special requirements"** to emphasize what matters most to you
6. **Test the prompt** by sending to MiniMax H3 and check if timing is accurate
7. **Iterate:** If first result isn't perfect, ask skill to adjust timing or style emphasis

---

## Example Usage Walkthrough

### User Request:
```
"I need a 10-second fight scene. Two martial artists, one-on-one duel. 
I want it to feel like a Sofia Coppola film—contemplative, intimate, 
beautiful despite the violence. Warehouse setting. Can you create the 
prompt for MiniMax H3?"
```

### Skill Response (Step-by-Step):

**Step 1: Confirmation**
```
Got it. Let me set this up:
- Martial Art: Hong Kong Kung Fu (assumed - tell me if different)
- Duration: 10 seconds
- Director: Sofia Coppola (contemplative, pastel, long holds)
- Scene: One-on-one duel
- Environment: Warehouse
- Mode: Detailed Mode (to show timing)

Ready to build the timing chart?
```

**Step 2: Timing Chart**
```
| Time | Camera | Fighter A | Fighter B | Audio |
| 0.0-1.5s | Static wide, 12m | Ready stance | Ready stance | Ambient |
| 1.5-2.0s | Slow push-in (1m) | Circles | Mirrors | Footsteps |
[... continues ...]
| 9.0-10.0s | Slow arc pull-back | Reset stance | Reset stance | Breathing sync |
```

**Step 3: Final Prompt**
```
Task type: T2VA
Duration: 10 seconds

[Shot 1] At 0.0s, the camera is positioned wide and static, 
12 meters from two martial artists facing off...

[Shot 2] At 1.5s, the camera slowly pushes in toward the fighters 
over 0.5 seconds...

[... continues through all shots ...]

integrated_multimodal_description: One-on-one martial arts duel 
in warehouse, Sofia Coppola aesthetic...
```

**Step 4: Certification**
```
✓ Timing verified: 10.0 seconds exactly
✓ Impact held at contemplative pace (0.4s vs standard 0.2s)
✓ Pastel desaturation evident throughout
✓ Climax positioned at 8.0-8.3s (outside final 10%)
✓ All actions as observable behavior (breathing, eye contact, muscle tension)
```

### User: "This looks good. Let me test it with MiniMax H3."

**[User sends prompt to MiniMax H3, receives video]**

### After Testing:

**User:** "Great! But can you make the exchange in the middle faster? It felt a bit slow."

**Skill:** "Absolutely. Let me adjust the timing chart for that sequence..."
[Regenerates chart with tighter exchange beats, keeping overall structure]

---

## API Integration (Advanced)

If you're integrating this skill with MiniMax H3 API:

1. **Extract the prompt** from the skill's output
2. **Parse the [Shot N] blocks** and timestamps
3. **Split into multiple prompt calls** if your API has limits
4. **Queue timing-accurate generations** using the 0.1s precision

Example pseudo-code:
```python
prompt_from_skill = """Task type: T2VA
Duration: 10 seconds
[Shot 1] At 0.0s, ...
[Shot 2] At 2.3s, ...
"""

# Parse and send to MiniMax H3
shots = parse_shots(prompt_from_skill)
for shot in shots:
    video_chunk = minimax_h3_api.generate(shot)
    # Sequence chunks based on timing
```

---

## Support & Feedback

### Common Questions:

**Q: Can I use this skill for non-MiniMax models?**  
A: Yes, but you may need to adjust prompt syntax. The skill is optimized for H3's syntax, but the timing/cinematography principles work for any video model.

**Q: What if my martial art isn't in the 7 core types?**  
A: Ask the skill to extrapolate from the closest type (e.g., Capoeira → HK kung fu choreography principles).

**Q: How do I adapt for TV commercial action instead of film?**  
A: Use the `minimax-h3-commercial-ad-director` skill (separate), or request short cuts (0.3-0.5s) and faster pacing.

**Q: Can I request action without a director style?**  
A: Not recommended—the skill always picks one deliberately. Default is Sofia Coppola for contemplative, or Kathryn Bigelow for kinetic.

---

## Version History

- **v1.0** (2026-08-14): Initial release
  - 8 action scene templates
  - 14 director styles
  - 7 martial art types
  - 45+ camera techniques
  - Quick/Detailed/Template/Director-Study modes

---

## License & Attribution

This skill integrates research from:
- Classic film theory (Kurosawa, Welles, Spielberg)
- Director visual databases (Coppola, Bigelow, Park, Villeneuve, etc.)
- Martial arts choreography studies (Jackie Chan, Bruce Lee, modern action direction)
- AI video model optimization research (MiniMax H3, Hailuo)

Use freely for personal projects, education, and commercial work.

---

**Ready to create your action scene?** Type:

```
"Create an action director prompt for a 10-second fight scene..."
```

The skill will take it from there!
