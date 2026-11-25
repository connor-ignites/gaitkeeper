# SPDX-License-Identifier: GPL-3.0-or-later
"""GaitKeeper's checks and fixes.

The maths modules (motion_math, body_rules, body, reactions, legs, adapt_math, report, names, cycle) run without
Blender; the rest read and write Blender actions. Everything is deterministic: no learned model, no network.
"""
