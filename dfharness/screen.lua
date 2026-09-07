--@ module=true
--luacheck: globals factory
local function build(...)
-- Read a character-layer buffer only when a native reader or caller needs it.
-- This object lives for one suspended request; never cache it across inputs.
local h=...
return function(deferred)
    local w,height=dfhack.screen.getWindowSize()
    assert(w>0 and height>0 and w*height<=120000,'Invalid or oversized UI buffer')
    local out={width=w,height=height,coordinates='zero-based UI character cells',
        captured=false,omitted='Decoded native interface; ASCII available through observe(view="full")'}
    local function rows()
        local result=h.array()
        for y=0,height-1 do
            local chars={}
            for x=0,w-1 do
                local pen=dfhack.screen.readTile(x,y)
                chars[#chars+1]=h.glyph(pen and pen.ch or 0)
            end
            local line=table.concat(chars):gsub(' +$','')
            if line:find('%S') then result[#result+1]={y=y,text=line} end
        end
        out.rows=result;out.captured=true;out.omitted=nil
        return result
    end
    setmetatable(out,{__index=function(_,key)if key=='rows' then return rows() end end})
    if not deferred then rows() end
    return out
end

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
