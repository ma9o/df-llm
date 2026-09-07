local source=...
local reads=0
local width,height=3,2
local env=setmetatable({dfhack={screen={getWindowSize=function()return width,height end,
    readTile=function(x,y)reads=reads+1;return {ch=y==0 and 65+x or 32} end}}},{__index=_ENV})
local capture=assert(load(source,'screen-fixture','t',env))({array=function()return {}end,glyph=string.char})
local names={}
local function test(name,fn)
    local ok,err=pcall(fn);assert(ok,name..': '..tostring(err));names[#names+1]=name
end
test('native-only UI metadata performs no character-buffer reads',function()
    local ui=capture(true)
    assert(reads==0 and ui.width==3 and ui.height==2 and ui.captured==false and ui.omitted)
    assert(rawget(ui,'rows')==nil)
    local encoded=require('json').encode(ui)
    assert(reads==0 and not encoded:find('rows'))
end)
test('fallback captures once and preserves zero-based nonempty rows',function()
    local ui=capture(true)
    assert(ui.rows[1].y==0 and ui.rows[1].text=='ABC' and #ui.rows==1)
    assert(reads==6 and ui.captured and not ui.omitted)
    assert(ui.rows==ui.rows and reads==6)
end)
test('explicit full UI captures immediately and oversized dimensions fail',function()
    reads=0
    assert(capture(false).captured and reads==6)
    width=120001
    assert(not pcall(capture,true))
    width=3
end)
return {passed=#names,tests=names,game_inputs=0}
