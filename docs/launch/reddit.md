# Reddit launch drafts

Drafts only. Nothing here has been posted. Post only once the repo is public and the v0.9.0 release is published, and replace the GIF line with the clip uploaded to Reddit itself.

## Before posting: rules and timing

The live rule pages couldn't be read from here: Reddit blocks automated reading. Open each sub's **Rules** in the sidebar (or `reddit.com/r/<sub>/about/rules`) and check these before posting:

- **r/blender**: a show-your-work sub. Check whether add-on posts need a flair (look for something like "Add-on" or "Resource") and whether self-promotion is limited. Usual safe shape: a video post showing the tool in use, with the GitHub link in the text or the first comment.
- **r/gamedev**: strict on self-promotion. Standalone "I made X" posts are often removed, and promotion is expected to go in the weekly threads. A post that teaches something (how foot-slide detection works, with the tool as the example) has a better chance. If unsure, message the mods first and ask whether a free open-source tool post is OK.
- **r/animation**: mostly finished animation. Check whether tools are allowed at all before posting; skip it if they aren't.
- Not r/blenderhelp: it's for questions.
- Reddit as a whole frowns on posting the same thing to many subs at once. Space the posts a few days apart, and answer comments.
- AI: no rule about AI-assisted tools was found, but a disclosure line is included below anyway, because people ask.

Timing is general guidance from social media scheduling blogs, not from the subs: a weekday morning, US Eastern time, Tuesday to Thursday, about 7 to 10 am.

Media: upload the before/after clip as a Reddit video (MP4, no sound needed) rather than linking a GIF. Use `docs/media/hero-walk-pops-and-skating.gif`'s source clip, or the punch and kangaroo clips as extra posts later.

## r/blender

**Title:** I made a free add-on that checks animation clips for foot sliding, pops and backward knees

**Post (video post, with this text):**

GaitKeeper is a free, open-source (GPL) add-on for Blender 4.2 and newer. Select an armature, press Check clips, and every clip gets PASS, WARN or FAIL with a plain-English reason: a foot skating while it should be planted, a knee bending past what a knee can do, a loop that hitches at the seam, a bone that snaps in one frame, a run that never leaves the ground.

It works on people and on animals (four legs, hoppers like kangaroos, even eight-legged spiders).

Check only reads your clips. Fix and Pose Adapt make a copy and never touch the original, and both undo.

It's a beta. I've run it on the Quaternius animation libraries and a few commercial packs, but rigs vary a lot, so if it misreads yours, a bug report with the rig attached would really help.

Link: https://github.com/connor-ignites/gaitkeeper

I built it with a lot of help from an AI coding assistant. The checks themselves are plain measurements: no AI model runs inside it.

## r/gamedev

**Title:** How I check game animation clips for foot sliding automatically (free Blender tool)

**Post (text post):**

Foot sliding is one of those faults players notice without being able to name it. I wanted a way to catch it before clips went into the engine, so I wrote a Blender add-on that measures it.

A foot counts as planted when it's near its lowest height and barely moving. While it's planted, any sideways travel is skating, measured in metres per second. The same pass catches feet sinking through the floor, knees bending backwards, one-frame pops (a bone turning much faster on one frame than the frames around it), loop seams that don't meet, and runs where both feet never leave the ground. Each clip gets PASS, WARN or FAIL with a reason a non-programmer can act on.

It also fixes some of these on a copy of the clip: it re-plants sliding feet (moving them 8 cm at most), closes loop seams and smooths pops. If the fixed copy checks worse than the original, it throws the copy away.

It's free and GPL, for Blender 4.2+, and in beta: https://github.com/connor-ignites/gaitkeeper

I'd like to hear where it gets things wrong, especially on rigs from other packs or engines. It was built with a lot of help from an AI coding assistant; the checks are plain measurements, with no AI model inside.

## r/animation (only if the rules allow tools)

**Title:** Free Blender add-on that flags foot sliding, pops and broken joints in game animation

**Post (video post):**

I made a free checker for game animation clips in Blender. It points at the frames where a foot skates, a joint snaps or a knee bends the wrong way, and says why in plain words. It never changes your original clip; fixes go on a copy. It's in beta, and I'd love feedback from animators on where it's too strict.

https://github.com/connor-ignites/gaitkeeper
