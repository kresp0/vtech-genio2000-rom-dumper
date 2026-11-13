-- MAME autoboot script for the README snapshots: reads SHOTS_SCRIPT, one command per line:
--   wait <s> | press <field> | snap | quit      (field = MAME input name, e.g. INTRO)
-- Copyright (C) 2026 Santiago Crespo
-- SPDX-License-Identifier: 0BSD
local machine = manager.machine
local fields = {}
for _, port in pairs(machine.ioport.ports) do
  for name, f in pairs(port.fields) do fields[name] = f end
end
local cmds = {}
for l in io.lines(os.getenv("SHOTS_SCRIPT")) do
  if not l:match("^%s*#") and l:match("%S") then cmds[#cmds + 1] = l end
end
local i, at, held = 1, 0, nil
emu.register_frame_done(function()
  local t = machine.time:as_double()
  if held and t >= held[2] then held[1]:set_value(0); held = nil end
  if t < at or held then return end
  local c = cmds[i]
  if not c then return end
  i = i + 1
  local cmd, arg = c:match("^(%S+)%s*(.*)$")
  if cmd == "wait" then at = t + tonumber(arg)
  elseif cmd == "press" then fields[arg]:set_value(1); held = {fields[arg], t + 0.15}; at = t + 0.3
  elseif cmd == "snap" then machine.video:snapshot()
  elseif cmd == "quit" then machine:exit() end
end)
