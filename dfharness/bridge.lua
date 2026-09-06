-- Executed in DFHack's suspended core context via RunCommand(lua, source).
-- Only plain Lua values cross the boundary. Never retain native DF pointers.
local req, glyph, character_reader, character_details, character_calculations = ...
local json = require('json')
local gui = require('gui')
local function array() return require('json.internal'):newArray{} end
local function check(test, message) if not test then error(message, 0) end end
local function integer(n, low, high, name)
    check(type(n) == 'number' and n == math.floor(n) and n >= low and n <= high,
        (name or 'value') .. ' must be an integer in [' .. low .. ', ' .. high .. ']')
    return n
end
local function pos(p) return {x=p.x, y=p.y, z=p.z} end
local function text(s) return dfhack.df2utf(s or '') end
local function optional(fn)
    local ok, value = pcall(fn)
    if ok then return value end
end

dfhack.df_llm_session = dfhack.df_llm_session or {serial=0, receipts={}, order={}}
local session = dfhack.df_llm_session
session.dispatches = session.dispatches or {}
session.dispatch_order = session.dispatch_order or {}
session.interrupt_requests = session.interrupt_requests or {}
session.interrupt_order = session.interrupt_order or {}

local function copy(value) return require('json.internal'):new{strictTypes=true}:decode(json.encode(value,{pretty=false})) end

local ui_rows
local function travel_info()
    local a=df.global.adventure
    local active=a.menu==df.ui_advmode_menu.Travel
    local army=df.army.find(a.player_army_id)
    local p
    if active and a.travel_not_moved~=0 then
        p={x=a.travel_origin_x,y=a.travel_origin_y,z=a.travel_origin_z}
    elseif army then p=pos(army.pos) end
    local exception=df.adventure_travel_exception_type[a.travel_exception_type]
    return {active=active,position=p,position_source=p and (army and a.travel_not_moved==0 and 'player_army' or 'travel_origin'),
        coordinates='travel tiles (16 local tiles; 3 per embark tile; 48 per world region)',
        not_moved=a.travel_not_moved~=0,site_zoom=a.site_level_zoom~=0,
        exception={type=exception,id=a.travel_exception_id,message=text(a.message)},
        world_size={x=df.global.world.world_data.world_width*48,y=df.global.world.world_data.world_height*48}}
end
local function status(ui)
    local screen = dfhack.gui.getCurViewscreen(true)
    local loaded = dfhack.isMapLoaded()
    local adventure = dfhack.isWorldLoaded() and dfhack.world.isAdventureMode()
    local phase = adventure and df.adventure_game_loop_type[df.global.adventure.player_control_state] or nil
    local adventurer = adventure and dfhack.world.getAdventurer() or nil
    local out = {
        df_version=dfhack.getDFVersion(), dfhack_version=dfhack.getDFHackVersion(),
        screen=tostring(screen):match('<([^:>]+)') or tostring(screen),
        focus=dfhack.gui.getCurFocus(true), map_loaded=loaded,
        mode=adventure and 'adventure' or (loaded and dfhack.world.isFortressMode() and 'fortress' or 'menus'),
        ready_for_input=not (adventure and df.viewscreen_dungeonmodest:is_instance(screen)
            and phase ~= 'TAKING_INPUT' and phase ~= 'TAKING_TOO_LONG_INPUT'),
        turn_phase=phase, action_serial=session.serial,
    }
    out.open_panels=array()
    local running=session.active_dispatch and session.dispatches[session.active_dispatch]
    if running then
        out.active_dispatch={id=session.active_dispatch,action=running.workflow.action,
            task_index=running.workflow.context.task_index or 0,last_action_id=running.last_action_id,
            interrupted=running.interrupted or false}
    end
    if adventure then
        local a=df.global.adventure
        out.processing={offload_timer=a.offload_timer,long_action_duration=a.long_action_duration,
            sleeping=a.sleeping,wait_timer=a.wait_timer}
        out.adventure_menu=df.ui_advmode_menu[df.global.adventure.menu]
        out.travel=travel_info()
        if df.global.game.main_interface.help.open then out.open_panels[#out.open_panels+1]='help' end
        local panels=df.global.game.main_interface.adventure
        for _,name in ipairs({'option_list','inventory','jump','conversation','perform','attack',
            'combat_pref','aim_projectile','companions','announcements','sleep','movement_options',
            'travel','barter','abilities','create','assume_identity','journal_outliner','look'}) do
            if optional(function() return panels[name].open end) then out.open_panels[#out.open_panels+1]=name end
        end
        if df.global.adventure.reaction_moment.open then out.open_panels[#out.open_panels+1]='reaction_moment' end
        ui=ui or ui_rows()
        local help=df.global.game.main_interface.help
        if help.open then
            out.modal={kind='help',title=text(help.header),button='Okay',dismissible=true}
            out.modal.text=optional(function()
                local lines=array()
                for _,box in ipairs(help.text) do
                    local words={};local row
                    for _,word in ipairs(box.word) do
                        if row and word.py~=row then lines[#lines+1]=table.concat(words,' ');words={} end
                        row=word.py;words[#words+1]=text(word.str)
                    end
                    if #words>0 then lines[#lines+1]=table.concat(words,' ') end
                end
                return #lines>0 and lines or nil
            end)
        elseif #out.focus==1 and out.focus[1]=='dungeonmode/Default' then
            local labels={}
            for _,row in ipairs(ui.rows) do labels[row.text:match('^%s*(.-)%s*$')]=true end
            if labels.More or labels.Okay then
                out.modal={kind='announcement',button=labels.More and 'More' or 'Okay',dismissible=true}
            else
                local combined={}
                for _,row in ipairs(ui.rows) do combined[#combined+1]=row.text end
                local contents=table.concat(combined,'\n')
                if contents:find('a Continue action',1,true) and contents:find('b Stop action',1,true)
                    and contents:find('c Finish action',1,true) then
                    out.modal={kind='action_prompt',dismissible=false,response_verified=false,
                        choices={'Continue action','Stop action','Finish action'}}
                end
            end
        end
        if phase=='TAKING_TOO_LONG_INPUT' and not out.modal then
            out.modal={kind='action_prompt',dismissible=false,response_verified=false,
                choices={'Continue action','Stop action','Finish action'}}
        end
        if not out.modal and (a.offload_timer>0 or a.long_action_duration>0 or a.sleeping~=0 or a.wait_timer>0) then
            out.ready_for_input=false
        end
    end
    out.can_move=loaded and adventure and out.ready_for_input and out.screen=='viewscreen_dungeonmodest'
        and #out.focus==1 and out.focus[1]=='dungeonmode/Default' and #out.open_panels==0 and not out.modal or false
    if dfhack.isWorldLoaded() then
        out.paused=df.global.pause_state
        out.world_frame=df.global.world.frame_counter
        out.year=df.global.cur_year
        out.year_tick=df.global.cur_year_tick
        out.save=dfhack.world.ReadWorldFolder()
    end
    if loaded then
        local x,y,z = dfhack.maps.getTileSize()
        out.map_size={x=x,y=y,z=z}
        local g=df.global.gps
        out.viewport={origin={x=df.global.window_x,y=df.global.window_y,z=df.global.window_z},
            zoom=g.viewport_zoom_factor,ui_tile_width=g.tile_pixel_x,ui_tile_height=g.tile_pixel_y}
    end
    if adventurer then out.adventurer_id=adventurer.id; out.position=pos(adventurer.pos) end
    return out
end

ui_rows=function()
    local w,h = dfhack.screen.getWindowSize()
    check(w > 0 and h > 0 and w*h <= 120000, 'Invalid or oversized UI buffer')
    local rows = array()
    for y=0,h-1 do
        local chars={}
        for x=0,w-1 do
            local pen=dfhack.screen.readTile(x,y)
            chars[#chars+1]=glyph(pen and pen.ch or 0)
        end
        local line=table.concat(chars):gsub(' +$','')
        if line:find('%S') then rows[#rows+1]={y=y,text=line} end
    end
    return {width=w,height=h,rows=rows,coordinates='zero-based UI character cells'}
end

local function state_id(s, ui, effects_only)
    local parts={s.screen, table.concat(s.focus,'|'), tostring(s.world_frame),
        tostring(s.year), tostring(s.year_tick), tostring(s.save), tostring(s.turn_phase),
        tostring(s.adventurer_id), effects_only and '' or tostring(s.action_serial), tostring(s.adventure_menu),
        table.concat(s.open_panels,'|'), tostring(ui.width), tostring(ui.height)}
    if s.position then parts[#parts+1]=('%d,%d,%d'):format(s.position.x,s.position.y,s.position.z) end
    if s.viewport then
        local v=s.viewport
        parts[#parts+1]=('%d,%d,%d,%d,%d,%d'):format(v.origin.x,v.origin.y,v.origin.z,
            v.zoom,v.ui_tile_width,v.ui_tile_height)
    end
    if s.travel then parts[#parts+1]=json.encode(s.travel,{pretty=false}) end
    for _,row in ipairs(ui.rows) do
        -- Premium travel's solid-block markers blink without changing input
        -- state. Preserve text/coordinates/prompts, but exclude that decoration.
        local line=s.adventure_menu=='Travel' and row.text:gsub('█',' '):gsub(' +$','') or row.text
        if line:find('%S') then parts[#parts+1]=row.y .. ':' .. line end
    end
    return dfhack.internal.md5(table.concat(parts,'\n'))
end

local function unit_info(u)
    local x,y,z=dfhack.units.getPosition(u)
    return {id=u.id, name=text(dfhack.units.getReadableName(u)),
        race=text(dfhack.units.getRaceReadableName(u)),
        position=x and {x=x,y=y,z=z} or nil, alive=dfhack.units.isAlive(u)}
end

local function item_info(item,depth,budget,location,seen)
    depth=depth or 0; budget=budget or {remaining=300}; seen=seen or {}
    budget.remaining=budget.remaining-1
    local quality=item:getQuality()
    local out={id=item.id,description=text(dfhack.items.getReadableDescription(item)),
        type=df.item_type[item:getType()],subtype=item:getSubtype(),stack_size=item:getStackSize(),
        quality=quality,wear=optional(function() return item:getWear() end),
        material=optional(function() return text(dfhack.matinfo.decode(item):toString()) end),
        weight_raw=optional(function() return {whole=item.weight.whole,fraction=item.weight.fraction} end),
        weight_computed=optional(function() return item.flags.weight_computed end),
        volume_raw=optional(function() return item:getVolume() end),location=location}
    local maker=optional(function() return item:getMakerRace() end)
    if maker and maker>=0 then
        out.fit={maker_race_id=maker,maker_species=optional(function() return text(df.global.world.raws.creatures.all[maker].name[0]) end),
            wearable_now='unknown'}
    end
    local def=dfhack.items.getSubtypeDef(item:getType(),item:getSubtype())
    if def then
        out.definition={id=def.id,name=text(def.name)}
        out.armor=optional(function() return {coverage=def.props.coverage,layer=def.props.layer,
            layer_size=def.props.layer_size,layer_permit=def.props.layer_permit} end)
        if item:getType()==df.item_type.WEAPON then
            out.weapon={skill=df.job_skill[def.skill_melee],minimum_size=def.minimum_size,
                two_handed_size=def.two_handed,attacks=array()}
            for _,a in ipairs(def.attacks) do
                out.weapon.attacks[#out.weapon.attacks+1]={verb=text(a.verb_2nd),edged=a.edged,
                    contact=a.contact,penetration=a.penetration,velocity_mult=a.velocity_mult}
            end
        end
    end
    if seen[item.id] then out.contents_truncated=true; return out end
    seen[item.id]=true
    local children=dfhack.items.getContainedItems(item)
    if #children>0 then
        out.contents=array()
        for _,child in ipairs(children) do
            if depth>=(budget.max_depth or 4) or budget.remaining<=0 then
                out.contents_truncated=true;out.contents_total=#children;break
            end
            if budget.include_hidden or not child.flags.hidden then
                local child_location=copy(location or {});child_location.container_id=item.id
                child_location.mode=nil;child_location.body_part_id=nil
                out.contents[#out.contents+1]=item_info(child,depth+1,budget,child_location,seen)
            end
        end
    end
    return out
end

local function item_location(item)
    local u=dfhack.world.getAdventurer()
    if not u or item.flags.hidden then return nil end
    local outer=dfhack.items.getOuterContainerRef(item)
    if outer and outer.object and df.unit:is_instance(outer.object) then
        if outer.object.id~=u.id then return nil end
        local loc={kind='inventory',unit_id=u.id}
        local container=dfhack.items.getContainer(item)
        if container then loc.container_id=container.id end
        for _,entry in ipairs(u.inventory) do
            if entry.item.id==item.id then loc.mode=df.inv_item_role_type[entry.mode];loc.body_part_id=entry.body_part_id;break end
        end
        return loc
    end
    local root=item
    for _=1,16 do
        local container=dfhack.items.getContainer(root)
        if not container then break end
        root=container
    end
    if root.flags.on_ground and not root.flags.hidden and dfhack.maps.isTileVisible(root.pos.x,root.pos.y,root.pos.z) then
        local loc={kind='ground',position=pos(root.pos),root_item_id=root.id}
        local container=dfhack.items.getContainer(item)
        if container then loc.container_id=container.id end
        return loc
    end
end

local function nearby_items(s,radius)
    local out=array();local budget={remaining=500};local p=s.position
    if not p or not s.map_loaded then return out end
    radius=integer(radius or 20,0,50,'radius')
    local mx,my=dfhack.maps.getTileSize()
    local x0,x1=math.max(0,p.x-radius),math.min(mx-1,p.x+radius)
    local y0,y1=math.max(0,p.y-radius),math.min(my-1,p.y+radius)
    for bx=x0//16,x1//16 do for by=y0//16,y1//16 do
        local block=dfhack.maps.getTileBlock(bx*16,by*16,p.z)
        if block then for _,id in ipairs(block.items) do
            local item=df.item.find(id)
            if item and item.flags.on_ground and not item.flags.hidden and item.pos.z==p.z
                and item.pos.x>=x0 and item.pos.x<=x1 and item.pos.y>=y0 and item.pos.y<=y1
                and dfhack.maps.isTileVisible(item.pos.x,item.pos.y,item.pos.z) then
                if budget.remaining<=0 then return out,true end
                out[#out+1]=item_info(item,0,budget,{kind='ground',position=pos(item.pos),root_item_id=item.id})
            end
        end end
    end end
    table.sort(out,function(a,b)return a.id<b.id end)
    return out,false
end

local function menu_info(ui)
    local a=df.global.game.main_interface.adventure
    local m,kind,list
    if a.inventory.open then m=a.inventory;kind='inventory';list=m.option_current
    elseif a.option_list.open then m=a.option_list;kind='option_list';list=m.option
    else return nil end
    local out={kind=kind,context=m.context,scroll=m.scroll_position,options=array(),
        context_item_id=optional(function()return m.context_item.id end),
        choosing_amount=optional(function()return m.doing_pickup_amount end)}
    for index,o in ipairs(list) do
        if #out.options>=500 then out.truncated=true;break end
        local label=df.new('string');local ok=pcall(function()o:getName(label)end)
        local name=ok and text(label.value) or nil;label:delete()
        local item=optional(function()return o:getItem()end) or optional(function()return o:getPickupItem()end)
        local container=optional(function()return o:getContainerItem()end)
        local action=df.adventure_option_type[o:getType()]
        local entry={index=index,id=('%s:%s:%d:%s:%s'):format(kind,action,index,tostring(item and item.id),tostring(container and container.id)),
            label=name,kind=action,item_id=item and item.id,container_id=container and container.id,depth=o.depth}
        -- Bind the native list index to the currently rendered letter and row.
        -- Both the ID and binding are rechecked inside the input request.
        local visible_index=index-m.scroll_position
        if visible_index>=0 and visible_index<26 and name then
            local letter=string.char(97+visible_index)
            for _,row in ipairs(ui.rows) do
                local key,shown=row.text:match('^%s*([a-z]) (.-)%s*$')
                if key==letter and (shown==name or (#shown>=8 and name:sub(1,#shown)==shown)) then
                    local first=row.text:find(letter..' ',1,true)
                    entry.click={x=utf8.len(row.text:sub(1,first-1))+2,y=row.y}
                    entry.visible=true;break
                end
            end
        end
        out.options[#out.options+1]=entry
    end
    return out
end

local function adventurer_info(full)
    local u=dfhack.world.getAdventurer()
    if not u then return nil end
    local out=unit_info(u)
    out.health={
        blood_count=optional(function() return u.body.blood_count end),
        blood_max=optional(function() return u.body.blood_max end),
        wounds=optional(function() return #u.body.wounds end),
        pain=optional(function() return u.counters.pain end),
        nausea=optional(function() return u.counters.nausea end),
        exhaustion=optional(function() return u.counters2.exhaustion end),
        hunger_timer=optional(function() return u.counters2.hunger_timer end),
        thirst_timer=optional(function() return u.counters2.thirst_timer end),
        sleepiness_timer=optional(function() return u.counters2.sleepiness_timer end),
    }
    local budget={remaining=full and 4096 or 300,max_depth=full and 16 or 4,include_hidden=full}
    out.inventory=array()
    for _,entry in ipairs(u.inventory) do
        if #out.inventory >= (full and 4096 or 120) or budget.remaining<=0 then out.inventory_truncated=true; break end
        local info=item_info(entry.item,0,budget,{kind='inventory',unit_id=u.id,
            mode=df.inv_item_role_type[entry.mode],body_part_id=entry.body_part_id})
        info.mode=df.inv_item_role_type[entry.mode];info.body_part_id=entry.body_part_id
        out.inventory[#out.inventory+1]=info
    end
    return out
end

local function tile_info(x,y,z)
    local d,o=dfhack.maps.getTileFlags(x,y,z)
    if not d or not dfhack.maps.isTileVisible(x,y,z) then return {visible=false} end
    local tt=dfhack.maps.getTileType(x,y,z)
    local a=df.tiletype.attrs[tt]
    return {visible=true,type=df.tiletype[tt],shape=df.tiletype_shape[a.shape],
        material=df.tiletype_material[a.material],liquid_depth=d.flow_size,
        liquid=d.flow_size > 0 and (d.liquid_type and 'magma' or 'water') or nil,
        building=o.building ~= 0, dig=df.tile_dig_designation[d.dig]}
end

local shape_glyph={EMPTY=' ',FLOOR='.',BOULDER='o',PEBBLES='.',WALL='#',
    FORTIFICATION='#',STAIR_UP='<',STAIR_DOWN='>',STAIR_UPDOWN='X',RAMP='^',
    RAMP_TOP='v',BROOK_BED='~',BROOK_TOP='~',TREE='T',SAPLING='t',SHRUB='"',
    BRANCH='T',TRUNK_BRANCH='T',TWIG='t',ENDLESS_PIT='O'}

local function map_view(s)
    local w=integer(req.width or 41,1,101,'width')
    local h=integer(req.height or 21,1,61,'height')
    local center=req.center or s.position or {x=df.global.window_x+w//2,y=df.global.window_y+h//2,z=df.global.window_z}
    local mx,my,mz=dfhack.maps.getTileSize()
    integer(center.x,0,mx-1,'center.x'); integer(center.y,0,my-1,'center.y'); integer(center.z,0,mz-1,'center.z')
    w=math.min(w,mx); h=math.min(h,my)
    local x0=math.max(0,math.min(mx-w,center.x-w//2))
    local y0=math.max(0,math.min(my-h,center.y-h//2))
    local z=center.z
    local cells,rows,walkable,liquids={},array(),array(),array()
    for y=y0,y0+h-1 do
        cells[y]={};local walkrow,liquidrow={},{}
        for x=x0,x0+w-1 do
            local t=tile_info(x,y,z)
            cells[y][x]=not t.visible and '?' or (t.liquid_depth > 0 and '~'
                or (t.building and 'B' or (shape_glyph[t.shape] or ':')))
            local group=t.visible and dfhack.maps.getWalkableGroup({x=x,y=y,z=z}) or 0
            walkrow[#walkrow+1]=group and group>0 and '1' or '0'
            liquidrow[#liquidrow+1]=t.visible and tostring(t.liquid_depth or 0) or '?'
        end
        walkable[#walkable+1]=table.concat(walkrow);liquids[#liquids+1]=table.concat(liquidrow)
    end
    local nearby=array()
    for _,u in ipairs(df.global.world.units.active) do
        local x,y,uz=dfhack.units.getPosition(u)
        if x and uz==z and x>=x0 and x<x0+w and y>=y0 and y<y0+h
            and dfhack.units.isVisible(u) and not dfhack.units.isHidden(u) then
            local info=unit_info(u)
            info.glyph=u.id==s.adventurer_id and '@' or 'u'
            cells[y][x]=info.glyph
            if #nearby < 100 then nearby[#nearby+1]=info end
        end
    end
    -- Ensure the player glyph wins if another unit occupies the same tile.
    local p=s.position
    if p and p.z==z and cells[p.y] and cells[p.y][p.x] then cells[p.y][p.x]='@' end
    for y=y0,y0+h-1 do
        local row={}
        for x=x0,x0+w-1 do row[#row+1]=cells[y][x] end
        rows[#rows+1]=table.concat(row)
    end
    return {source='semantic terrain from DFHack; not native classic rendering',
        origin={x=x0,y=y0,z=z},width=w,height=h,rows=rows,units=nearby,walkable=walkable,liquid_depths=liquids,
        legend={['@']='adventurer',u='visible creature (see units)',B='building',
            ['#']='wall/fortification',['.']='floor',['~']='liquid/brook',T='tree',
            ['<']='up stair',['>']='down stair',X='up/down stair',['^']='ramp',
            ['?']='unseen/unavailable',[' ']='open space',[':']='other terrain',
            o='boulder',t='sapling/twig',v='ramp top',O='endless pit',['"']='shrub'},
        visibility='DFHack isTileVisible plus isHidden for units; not a strict UI-only information boundary'}
end

local function observe()
    local ui=ui_rows()
    local s=status(ui)
    local out={status=s,ui=ui,state_id=state_id(s,ui),effect_id=state_id(s,ui,true)}
    if s.map_loaded and s.mode=='adventure' then
        out.adventurer=adventurer_info()
        out.nearby_items,out.nearby_items_truncated=nearby_items(s,req.radius)
        out.menu=menu_info(ui)
        if out.menu and out.menu.kind=='inventory' then
            local wear=false;local eligible={}
            for _,o in ipairs(out.menu.options)do
                if o.kind=='WEAR_ITEM' then wear=true;eligible[o.item_id]=true end
            end
            if wear then
                local function mark(items)
                    for _,i in ipairs(items)do
                        if i.fit then i.fit.wearable_now=eligible[i.id] or false end
                        if i.contents then mark(i.contents)end
                    end
                end
                mark(out.adventurer.inventory)
            end
        end
        if req.map ~= false then out.map=map_view(s) end
        -- Reports persist after the transient text has faded. IDs and speaker IDs
        -- distinguish a direct reply from somebody else's conversation nearby.
        out.reports=array()
        local reports=df.global.world.status.reports
        for i=math.max(0,#reports-80),#reports-1 do
            local r=reports[i]
            out.reports[#out.reports+1]={id=r.id,text=text(r.text),
                speaker_id=r.speaker_id,activity_id=r.activity_id,
                activity_event_id=r.activity_event_id,type=df.announcement_type[r.type],
                year=r.year,year_tick=r.time}
        end
        local c=df.global.game.main_interface.adventure.conversation
        if c.open then
            local function participants(event)
                local ids=array()
                if event then
                    for _,p in ipairs(event.participants) do ids[#ids+1]=p.unit_id end
                end
                return ids
            end
            local conv={selecting=c.selecting_conversation,filter=text(c.conv_string_filter),
                entering_filter=c.entering_conv_string_filter,choices=array(),options=array(),
                activity_id=c.conv_act and c.conv_act.id or nil,participants=participants(c.conv_actce)}
            for i,info in ipairs(c.conv_choice_info) do
                local lines={}
                for _,line in ipairs(info.title.text) do lines[#lines+1]=text(line.value) end
                conv.choices[#conv.choices+1]={index=i,label=table.concat(lines,' ')}
            end
            for i,option in ipairs(c.select_option) do
                local label=df.new('string')
                local ok,err=pcall(function() option:getName(label) end)
                local value=ok and text(label.value) or tostring(err)
                label:delete()
                conv.options[#conv.options+1]={index=i,label=value,
                    unit_id=optional(function() return option.unit_id end),
                    participants=participants(optional(function() return option.conv_actev end))}
            end
            out.conversation=conv
        end
    end
    return out
end

local function click(x,y,button)
    local g,e=df.global.gps,df.global.enabler
    integer(x,0,g.dimx-1,'x'); integer(y,0,g.dimy-1,'y')
    check(button=='left' or button=='right' or button=='middle','Invalid mouse button')
    local old={g.mouse_x,g.mouse_y,g.precise_mouse_x,g.precise_mouse_y,e.tracking_on}
    local ok,err=xpcall(function()
        g.mouse_x=x; g.mouse_y=y
        g.precise_mouse_x=math.floor((x+0.5)*g.tile_pixel_x)
        g.precise_mouse_y=math.floor((y+0.5)*g.tile_pixel_y)
        gui.simulateInput(dfhack.gui.getCurViewscreen(true),
            button=='left' and '_MOUSE_L' or (button=='right' and '_MOUSE_R' or '_MOUSE_M'))
    end,debug.traceback)
    g.mouse_x=old[1];g.mouse_y=old[2];g.precise_mouse_x=old[3];g.precise_mouse_y=old[4];e.tracking_on=old[5]
    check(ok,err)
end

local directions={n='N',s='S',e='E',w='W',ne='NE',nw='NW',se='SE',sw='SW',up='UP',down='DOWN'}

local function act()
    check(type(req.request_id)=='string' and #req.request_id<=100,'request_id is required')
    local previous=session.receipts[req.request_id]
    if previous then
        check(previous.request==json.encode(req,{pretty=false}),'request_id reused with different arguments')
        return {action_id=req.request_id,duplicate=true,dispatch=previous.dispatch}
    end
    local ui=ui_rows()
    local s=status(ui)
    local a=req.action
    check(type(a)=='table','action must be an object')
    check(s.ready_for_input or a.type=='resume','Adventure turn is processing; observe or wait-ready before sending input')
    if session.pending then
        local last=session.receipts[session.pending]
        check(a.type=='resume' or not last or last.settled,'Previous action has not settled; wait-ready first')
    end
    if req.expect then check(req.expect==state_id(s,ui),'Stale observation; observe again before acting') end
    if a.type=='dismiss' then
        check(s.modal and s.modal.dismissible,'No supported help or announcement prompt to dismiss')
        a={type='click_text',text=s.modal.button}
    end
    local key=a.key
    if a.type=='move' or a.type=='wait' then
        check(s.mode=='adventure' and s.screen=='viewscreen_dungeonmodest', 'Movement requires an active local adventure')
        check(s.can_move, 'Close the current menu before moving or waiting')
        if a.type=='move' then
            check(type(a.direction)=='string' and directions[a.direction:lower()],'Invalid movement direction')
            key='A_MOVE_'..directions[a.direction:lower()]
        else key='A_SHORT_WAIT' end
    elseif a.type=='key' then
        check(type(key)=='string','key must be an interface_key name')
    elseif a.type=='select_option' then
        check(not s.modal,'Handle the current prompt before selecting an option')
        local menu=menu_info(ui);local found
        if menu then for _,o in ipairs(menu.options)do if o.id==a.option_id then found=o;break end end end
        check(found and found.visible and found.click,'Option is absent or not visibly bound; observe or scroll first')
        a={type='click',x=found.click.x,y=found.click.y,button='left'}
    elseif a.type=='resume' then
        -- Observe/wait and apply the controller's dispatch policy, without
        -- resubmitting the original game input.
    elseif a.type=='action_prompt' then
        check(s.modal and s.modal.kind=='action_prompt','No Continue/Stop/Finish prompt is present')
        key=({continue='OPTION1',stop='OPTION2',finish='OPTION3'})[a.choice]
        check(key~=nil,'choice must be continue, stop, or finish')
    elseif a.type=='click' then
        integer(a.x,0,df.global.gps.dimx-1,'x');integer(a.y,0,df.global.gps.dimy-1,'y')
    elseif a.type=='select_unit' then
        -- A map click has different meanings in different menus. Limit this
        -- action to the creature picker so it cannot accidentally attack/move.
        check(s.mode=='adventure' and s.screen=='viewscreen_dungeonmodest' and
            #s.focus==1 and s.focus[1]=='dungeonmode/Conversation',
            'Selecting a conversation target requires the adventure conversation view')
        local c=df.global.game.main_interface.adventure.conversation
        check(c.open and c.selecting_conversation and not s.modal,
            'Open the conversation creature picker and dismiss help before selecting a unit')
        integer(a.unit_id,0,2147483647,'unit_id')
        local u=df.unit.find(a.unit_id)
        check(u and dfhack.units.isVisible(u) and not dfhack.units.isHidden(u),'Unit is not visible')
        local x,y,z=dfhack.units.getPosition(u)
        check(x~=nil,'Unit has no map position')
        local g=df.global.gps
        local dx,dy=x-df.global.window_x,y-df.global.window_y
        check(z==df.global.window_z and dx>=0 and dy>=0 and dx<g.main_viewport.dim_x
            and dy<g.main_viewport.dim_y,'Unit is outside the current map viewport')
        local px,py
        if df.global.init.display.flag.USE_GRAPHICS then
            local size=g.viewport_zoom_factor/4
            px=(dx+0.5)*size;py=(dy+0.5)*size
        else px=(dx+0.5)*g.tile_pixel_x;py=(dy+0.5)*g.tile_pixel_y end
        local ux,uy=math.floor(px/g.tile_pixel_x),math.floor(py/g.tile_pixel_y)
        integer(ux,0,g.dimx-1,'unit UI x');integer(uy,0,g.dimy-1,'unit UI y')
        -- Reject text-covered cells (conversation buttons/help/quest panels).
        for _,row in ipairs(ui.rows) do
            if math.abs(row.y-uy)<=1 then
                local first=utf8.offset(row.text,math.max(1,ux-2))
                local last=utf8.offset(row.text,math.min(utf8.len(row.text)+1,ux+5))
                check(not (first and row.text:sub(first,last and last-1 or -1):find('%S')),
                    'Unit is covered by UI text; move or adjust the viewport first')
            end
        end
        check(not df.global.init.display.flag.USE_GRAPHICS or
            (math.floor((ux+0.5)*g.tile_pixel_x/(g.viewport_zoom_factor/4))==dx and
             math.floor((uy+0.5)*g.tile_pixel_y/(g.viewport_zoom_factor/4))==dy),
             'UI cells are too coarse for this map zoom; zoom in before selecting a unit')
        a={type='click',x=ux,y=uy,button='left'}
    elseif a.type=='click_text' then
        check(type(a.text)=='string' and #a.text>0,'text must be nonempty')
        local matches={}
        for _,row in ipairs(ui_rows().rows) do
            local start=1
            while true do
                local first,last=row.text:find(a.text,start,true)
                if not first then break end
                matches[#matches+1]={x=utf8.len(row.text:sub(1,first-1))+math.floor(utf8.len(a.text)/2),y=row.y}
                start=last+1
            end
        end
        check(#matches==1,'Expected exactly one visible text match; found '..#matches)
        a={type='click',x=matches[1].x,y=matches[1].y,button=a.button}
    elseif a.type=='text' then
        check(type(a.text)=='string' and #a.text>0 and #a.text<=200,'text must be 1..200 ASCII bytes')
        check(not a.text:find('[^ -~]'),'text only accepts printable ASCII; use key for Enter/Escape')
    else error('Unknown action type: '..tostring(a.type),0) end
    if key then check(df.interface_key[key]~=nil,'Unknown interface_key: '..tostring(key)) end
    -- Register before input: an input failure can have partial effects and must not be retried blindly.
    local receipt={request=json.encode(req,{pretty=false}),settled=false}
    local before_effect_id=state_id(s,ui,true)
    local reports=s.map_loaded and df.global.world.status.reports
    local report_id=reports and #reports>0 and reports[#reports-1].id or -1
    if req.parent_dispatch then
        local parent=session.dispatches[req.parent_dispatch]
        check(parent and session.active_dispatch==req.parent_dispatch,'Dispatch is no longer active')
        if parent.interrupted then return {interrupted=true,action_id=req.request_id} end
        check(type(req.workflow)=='table','Missing workflow checkpoint')
        parent.workflow=copy(req.workflow)
        parent.last_action_id=req.request_id
    end
    session.receipts[req.request_id]=receipt
    session.order[#session.order+1]=req.request_id
    if #session.order>128 then session.receipts[table.remove(session.order,1)]=nil end
    session.pending=req.request_id
    session.serial=session.serial+1
    local ok,err=xpcall(function()
        if key then gui.simulateInput(dfhack.gui.getCurViewscreen(true),key)
        elseif a.type=='click' then click(a.x,a.y,a.button or 'left')
        elseif a.type=='resume' then -- no input
        else
            for i=1,#a.text do
                gui.simulateInput(dfhack.gui.getCurViewscreen(true),('STRING_A%03d'):format(a.text:byte(i)))
            end
        end
    end,debug.traceback)
    receipt.error=not ok and tostring(err) or nil
    dfhack.timeout(2,'frames',function() receipt.settled=true end)
    return {action_id=req.request_id,accepted=ok,error=receipt.error,
        before_effect_id=before_effect_id,before_report_id=report_id}
end

local function dispatch()
    check(type(req)=='table','Request must be an object')
    if req.op=='status' then return status()
    elseif req.op=='character_status' then
        local ui=ui_rows();local s=status(ui)
        local result={schema_version=2,format='character_status',status=s,
            state_id=state_id(s,ui),effect_id=state_id(s,ui,true),available=false}
        local u=s.mode=='adventure' and dfhack.world.getAdventurer()
        if not u then result.reason='No active adventurer is available';return result end
        check(type(character_reader)=='function','Character reader was not supplied by this client')
        check(type(character_details)=='function','Character details reader was not supplied by this client')
        check(type(character_calculations)=='table','Character calculations were not supplied by this client')
        result.character=character_reader(u,adventurer_info(true),{array=array,text=text,ui=ui,status=s,
            details_reader=character_details,calculations=character_calculations})
        result.available=true
        return result
    elseif req.op=='observe' then return observe()
    elseif req.op=='act' then return act()
    elseif req.op=='begin_dispatch' then
        check(type(req.request_id)=='string' and #req.request_id>0 and #req.request_id<=100,'Invalid request_id')
        local previous=session.dispatches[req.request_id]
        local signature=json.encode(req,{pretty=false})
        if previous then
            check(previous.request==signature,'request_id reused with different arguments')
            return {duplicate=true,dispatch=previous.dispatch,view=observe(),action_id=req.request_id}
        end
        local view=observe()
        if req.expect then check(req.expect==view.state_id,'Stale observation; observe again before acting') end
        local workflow={action=req.action,context=require('json.internal'):newObject{}}
        local resume_id=req.action and req.action.type=='resume' and req.action.dispatch_id
        local last_action_id
        if resume_id then
            local prior=session.dispatches[resume_id]
            check(prior,'Unknown dispatch (game restarted or receipt expired)')
            check(not prior.resumed_by,'Dispatch was already resumed; use its latest continuation')
            check(prior.save==view.status.save and prior.adventurer_id==view.status.adventurer_id,
                'Cannot resume in a different save or adventurer')
            check(not session.active_dispatch or session.active_dispatch==resume_id,'Another dispatch is active')
            workflow=copy(prior.workflow);last_action_id=prior.last_action_id
        else
            local active=session.active_dispatch and session.dispatches[session.active_dispatch]
            check(not active or active.interrupted,'Another dispatch is active; interrupt or resume it first')
        end
        local record={request=signature,workflow=workflow,save=view.status.save,
            adventurer_id=view.status.adventurer_id,last_action_id=last_action_id,
            interrupted=session.interrupt_requests[req.request_id] or false}
        session.interrupt_requests[req.request_id]=nil
        session.dispatches[req.request_id]=record
        if resume_id then session.dispatches[resume_id].resumed_by=req.request_id end
        session.dispatch_order[#session.dispatch_order+1]=req.request_id
        if #session.dispatch_order>128 then session.dispatches[table.remove(session.dispatch_order,1)]=nil end
        session.active_dispatch=req.request_id
        return {action_id=req.request_id,view=view,workflow=workflow,last_action_id=last_action_id}
    elseif req.op=='finish_dispatch' then
        local record=session.dispatches[req.action_id]
        check(record,'Unknown dispatch')
        record.dispatch=copy(req.dispatch);record.workflow=copy(req.workflow)
        if session.active_dispatch==req.action_id then session.active_dispatch=nil end
        return {recorded=true}
    elseif req.op=='interrupt' then
        check(type(req.dispatch_id)=='string' and #req.dispatch_id>0 and #req.dispatch_id<=100,'Invalid dispatch_id')
        local record=session.dispatches[req.dispatch_id]
        if record then record.interrupted=true
        else
            session.interrupt_requests[req.dispatch_id]=true
            session.interrupt_order[#session.interrupt_order+1]=req.dispatch_id
            if #session.interrupt_order>128 then session.interrupt_requests[table.remove(session.interrupt_order,1)]=nil end
        end
        return {dispatch_id=req.dispatch_id,interruption_requested=true,active=session.active_dispatch==req.dispatch_id}
    elseif req.op=='record_dispatch' then
        local receipt=session.receipts[req.action_id]
        check(receipt,'Unknown dispatch receipt (game restarted or receipt expired)')
        check(type(req.dispatch)=='table','dispatch result must be an object')
        receipt.dispatch=req.dispatch
        return {recorded=true}
    elseif req.op=='poll' then
        local s=status()
        local receipt=session.receipts[req.action_id or session.pending]
        check(not req.action_id or receipt,'Unknown action receipt (game restarted or receipt expired)')
        local running=req.dispatch_id and session.dispatches[req.dispatch_id]
        return {ready=s.ready_for_input and (not receipt or receipt.settled),status=s,
            interrupted=running and (running.interrupted or session.active_dispatch~=req.dispatch_id) or false,
            action_error=receipt and receipt.error}
    elseif req.op=='items' then
        local s=status();local items,truncated=nearby_items(s,req.radius)
        return {state_id=state_id(s,ui_rows()),items=items,truncated=truncated,position=s.position}
    elseif req.op=='item' then
        integer(req.item_id,0,2147483647,'item_id')
        local item=df.item.find(req.item_id)
        local location=item and item_location(item)
        check(location,'Item is not carried by the adventurer or on visible ground')
        return item_info(item,0,nil,location)
    elseif req.op=='keys' then
        local out=array()
        local query=(req.filter or ''):upper()
        for id=df.interface_key._first_item,df.interface_key._last_item do
            local name=df.interface_key[id]
            if type(name)=='string'
                and name:find(query,1,true) then out[#out+1]=name end
        end
        table.sort(out)
        return out
    elseif req.op=='inspect' then
        check(dfhack.isMapLoaded(),'No map loaded')
        local mx,my,mz=dfhack.maps.getTileSize()
        local x=integer(req.x,0,mx-1,'x');local y=integer(req.y,0,my-1,'y');local z=integer(req.z,0,mz-1,'z')
        local out=tile_info(x,y,z)
        out.position={x=x,y=y,z=z};out.items=array();out.units=array()
        if out.visible then
            local block=dfhack.maps.getTileBlock(x,y,z)
            for _,id in ipairs(block.items) do
                local item=df.item.find(id)
                if item and item.flags.on_ground and not item.flags.hidden
                    and item.pos.x==x and item.pos.y==y and item.pos.z==z then
                    if #out.items>=100 then out.items_truncated=true;break end
                    out.items[#out.items+1]=item_info(item,0,nil,{kind='ground',position=pos(item.pos),root_item_id=item.id})
                end
            end
            for _,u in ipairs(df.global.world.units.active) do
                local ux,uy,uz=dfhack.units.getPosition(u)
                if ux==x and uy==y and uz==z and not dfhack.units.isHidden(u) then
                    out.units[#out.units+1]=unit_info(u)
                end
            end
        end
        return out
    end
    error('Unknown operation: '..tostring(req.op),0)
end

local ok,result=xpcall(dispatch,debug.traceback)
return ok and {ok=true,result=result} or {ok=false,error=tostring(result)}
