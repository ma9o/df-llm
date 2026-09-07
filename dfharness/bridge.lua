--@ module=true
--luacheck: globals factory
local function build(...)
-- Executed in DFHack's suspended core context via RunCommand(lua, source).
-- Only plain Lua values cross the boundary. Never retain native DF pointers.
local req,modules = ...
local glyph=modules.glyph()
local character_reader,character_details,unit_reader=modules.character,modules.details,modules.unit
local character_calculations=modules.calculations and modules.calculations()
local interaction_reader,ui_reader,runtime_reader=modules.interactions,modules.ui,modules.runtime
local input_guard=modules.guard()
local wire=modules.wire()
local json = {encode=wire.encode}
local gui = require('gui')
local function array() return require('json.internal'):newArray{} end
local function check(test, message) if not test then error(message, 0) end end
local function integer(n, low, high, name)
    check(type(n) == 'number' and n == math.floor(n) and n >= low and n <= high,
        (name or 'value') .. ' must be an integer in [' .. low .. ', ' .. high .. ']')
    return n
end
local function pos(p) return {x=p.x, y=p.y, z=p.z} end
local function text(s)
    if s~=nil and type(s)~='string' then s=s.value end
    return dfhack.df2utf(s or '')
end
local function optional(fn)
    local ok, value = pcall(fn)
    if ok then return value end
end

local bindings=ui_reader({array=array,text=text,
    normalize_ui=function()gui.simulateInput(dfhack.gui.getCurViewscreen(true),{})end})
local aim=modules.aim({array=array,text=text,bindings=bindings})
local interactions=interaction_reader and interaction_reader({array=array,text=text,bindings=bindings,aim=aim})
local runtime=runtime_reader({array=array,text=text,bindings=bindings,calculations=character_calculations})
local screen_reader=modules.screen({array=array,glyph=glyph})
local read_reports=modules.reports({array=array,text=text})
local environment=modules.environment({array=array})
local movement=modules.movement({array=array,text=text,bindings=bindings})
local health=modules.health({array=array,same=function(a,b)return not next(wire.delta(a,b))end})
local burden=modules.burden()
local progress_reader=modules.progress({array=array,health=health,movement=movement,reports=read_reports})
local item_reader=modules.items({array=array})
local rest=modules.rest({array=array,bindings=bindings})
local saving=modules.saving({array=array,text=text,bindings=bindings,
    input=function(key)gui.simulateInput(dfhack.gui.getCurViewscreen(true),key)end})
local attack=modules.attack({array=array,bindings=bindings,copy=wire.clone})
local input_registered=false
local lifetime=modules.session()
local session=lifetime.open()

local copy=wire.clone

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
    local members=array()
    if army then for _,m in ipairs(army.members) do
        members[#members+1]={nemesis_id=m.nemesis_id,hunger_timer=m.hunger_timer,
            thirst_timer=m.thirst_timer,sleepiness_timer=m.sleepiness_timer}
    end end
    return {active=active,position=p,position_source=p and (army and a.travel_not_moved==0 and 'player_army' or 'travel_origin'),
        activity=runtime.army_activity(army),
        coordinates='travel tiles (16 local tiles; 3 per embark tile; 48 per world region)',
        not_moved=a.travel_not_moved~=0,site_zoom=a.site_level_zoom~=0,party_needs=members,
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
        ready_for_input=not df.viewscreen_loadgamest:is_instance(screen) and not
            (adventure and df.viewscreen_dungeonmodest:is_instance(screen)
            and phase ~= 'TAKING_INPUT' and phase ~= 'TAKING_TOO_LONG_INPUT'),
        turn_phase=phase, action_serial=session.serial,world_epoch=session.world_epoch,
        local_map_epoch=session.world_epoch..'.'..session.map_generation,
    }
    out.open_panels=array()
    local running=session.active_dispatch and session.dispatches[session.active_dispatch]
    if running then
        local ctx=running.workflow.context
        local leaf=ctx.stages and ctx.stages[(ctx.stage_index or 0)+1]
        out.active_dispatch={id=session.active_dispatch,action=running.workflow.action,
            task_index=(leaf and leaf.context or ctx).task_index or 0,last_action_id=running.last_action_id,
            stage_index=ctx.stage_index,stage_count=ctx.stages and #ctx.stages or nil,
            current_action=leaf and leaf.action or nil,
            interrupted=running.interrupted or false}
    end
    if adventure then
        local a=df.global.adventure
        -- getAdventurer() is nil while the local map is offloaded for travel.
        -- The player nemesis index remains available across that transition.
        local n=a.player_id>=0 and a.player_id<#df.global.world.nemesis.all and df.global.world.nemesis.all[a.player_id]
        if n then out.adventurer_id=n.unit_id;out.player_nemesis_id=n.id end
        out.processing={offload_timer=a.offload_timer,long_action_duration=a.long_action_duration,
            sleeping=a.sleeping,wait_timer=a.wait_timer}
        local save_ok,save_busy=pcall(runtime.saving)
        if save_ok then
            out.processing.saving=save_busy
            if save_busy then out.ready_for_input=false end
        else out.interface_unavailable=tostring(save_busy):sub(1,240);out.ready_for_input=false end
        out.adventure_menu=df.ui_advmode_menu[df.global.adventure.menu]
        out.travel=travel_info()
        if not out.travel.activity.available then
            out.interface_unavailable=out.travel.activity.reason;out.ready_for_input=false
        end
        local panels=runtime.panels()
        for name,open in pairs(panels.flags) do if open then out.open_panels[#out.open_panels+1]=name end end
        table.sort(out.open_panels)
        if not panels.available then out.interface_unavailable=panels.reason end
        if df.global.adventure.reaction_moment.open then out.open_panels[#out.open_panels+1]='reaction_moment' end
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
            local announcement=runtime.announcement()
            out.announcement_state=announcement
            if announcement.available then
                if announcement.open then
                    out.modal={kind='announcement',button=announcement.more and 'More' or 'Okay',
                        dismissible=true,source='native',scroll=announcement.scroll,lines=announcement.lines,
                        native_kind=announcement.native_kind,count=announcement.count}
                    if announcement.text then out.modal.text=array();out.modal.text[1]=announcement.text end
                end
            else
                -- Unknown native symbols retain the isolated text fallback.
                ui=ui or ui_rows()
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
        end
        if phase=='TAKING_TOO_LONG_INPUT' and not out.modal then
            out.modal={kind='action_prompt',dismissible=false,response_verified=false,
                choices={'Continue action','Stop action','Finish action'}}
        end
        if not out.modal and (a.offload_timer>0 or a.long_action_duration>0 or a.sleeping~=0 or a.wait_timer>0
            or out.travel.activity.active) then
            out.ready_for_input=false
        end
    end
    out.can_move=loaded and adventure and out.ready_for_input and out.screen=='viewscreen_dungeonmodest'
        and #out.focus==1 and out.focus[1]=='dungeonmode/Default' and #out.open_panels==0
        and not out.modal and not out.interface_unavailable or false
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
        out.map_origin={x=df.global.world.map.region_x*48,y=df.global.world.map.region_y*48,z=df.global.world.map.region_z}
        local g=df.global.gps
        out.viewport={origin={x=df.global.window_x,y=df.global.window_y,z=df.global.window_z},
            zoom=g.viewport_zoom_factor,ui_tile_width=g.tile_pixel_x,ui_tile_height=g.tile_pixel_y}
    end
    if adventurer then out.adventurer_id=adventurer.id; out.position=pos(adventurer.pos) end
    return out
end

ui_rows=function()
    return screen_reader(req.ui_mode=='native')
end

local native_guard
local guard_cache={}
local function state_id(s,ui,effects_only,raw_ui)
    local native=guard_cache[s]
    if not native then native=native_guard(s,ui);guard_cache[s]=native end
    if raw_ui then native=copy(native);native.complete=false end
    local id=input_guard(s,ui,native,effects_only)
    return raw_ui and ('u2:'..id:sub(4)) or id
end

local function unit_info(u)
    local x,y,z=dfhack.units.getPosition(u)
    return {id=u.id, name=text(dfhack.units.getReadableName(u)),
        race=text(dfhack.units.getRaceReadableName(u)),
        position=x and {x=x,y=y,z=z} or nil, alive=dfhack.units.isAlive(u)}
end

local function navigation_info(s,with_leads)
    local p=s.travel and s.travel.position
    if not (s.travel and s.travel.active) and s.position and s.map_origin then
        p={x=math.floor((s.map_origin.x+s.position.x)/16),y=math.floor((s.map_origin.y+s.position.y)/16)}
    end
    local out={position=p,coordinates='travel tiles (16 local tiles)',travel=s.travel}
    local function name(n) return text(dfhack.translation.translateName(n,true)) end
    local function site_info(site)
        local x1,y1=site.global_min_x*3,site.global_min_y*3
        local x2,y2=site.global_max_x*3+2,site.global_max_y*3+2
        local x,y=math.floor((x1+x2)/2),math.floor((y1+y2)/2)
        return {id=site.id,name=name(site.name),type=df.world_site_type[site.type],
            bounds={x1=x1,y1=y1,x2=x2,y2=y2},center={x=x,y=y},
            distance=p and math.max(math.abs(x-p.x),math.abs(y-p.y))}
    end
    if p then for _,site in ipairs(df.global.world.world_data.sites) do
        if p.x>=site.global_min_x*3 and p.x<=site.global_max_x*3+2
            and p.y>=site.global_min_y*3 and p.y<=site.global_max_y*3+2 then
            out.current_site=site_info(site)
            local r=site.realization
            local b=out.current_site.bounds
            local w,h=b.x2-b.x1+1,b.y2-b.y1+1
            if r and w<=51 and h<=51 and (not p.z or p.z==0) then
                local grid={source='native site travel grid; direction masks and forbidden_adv_travel flags',
                    origin={x=b.x1,y=b.y1},width=w,height=h,rows=array(),masks=array(),blocked=array(),
                    mask_encoding='two hex digits per tile: n=1,s=2,e=4,w=8,nw=16,sw=32,ne=64,se=128'}
                local bits={{'north',1},{'south',2},{'east',4},{'west',8},{'northwest',16},
                    {'southwest',32},{'northeast',64},{'southeast',128}}
                for y=0,h-1 do
                    local row,masks,blocked={},{},{}
                    for x=0,w-1 do
                        local mask=0
                        for _,bit in ipairs(bits) do if r.zoom_movemask[x][y][bit[1]] then mask=mask+bit[2] end end
                        row[#row+1]=glyph(r.zoom_tiles[x][y]);masks[#masks+1]=('%02x'):format(mask)
                        blocked[#blocked+1]=r.flags_map[x][y].forbidden_adv_travel and '1' or '0'
                    end
                    grid.rows[#grid.rows+1]=table.concat(row);grid.masks[#grid.masks+1]=table.concat(masks)
                    grid.blocked[#grid.blocked+1]=table.concat(blocked)
                end
                out.site_grid=grid
            else out.site_grid_unavailable='No supported surface travel grid is currently loaded' end
            break
        end
    end end
    if with_leads then
        local limit=integer(req.limit or 20,1,100,'limit')
        local n=s.player_nemesis_id and df.nemesis_record.find(s.player_nemesis_id)
        local info=n and n.figure and n.figure.info and n.figure.info.known_info
        out.leads=array();out.leads_source='Character-known group and beast rumors; no hostility or risk classification'
        if info and info.rumor_info then
            for i,e in ipairs(info.rumor_info.events) do
                if i>=4096 then out.rumors_truncated=true;break end
                local tag=df.entity_event_type[e.type]
                if tag=='group' or tag=='beast' then
                    local d=e.data[tag];local site=df.world_site.find(d.site_id)
                    if site then
                        local lead={kind=tag,site=site_info(site),outmoded=e.flag.outmoded,year=e.year,year_tick=e.year_tick}
                        if tag=='group' then
                            local ent=df.historical_entity.find(d.entity_id)
                            lead.entity={id=d.entity_id,name=ent and name(ent.name)}
                        else
                            local hf=df.historical_figure.find(d.histfig_id)
                            lead.figure={id=d.histfig_id,name=hf and name(hf.name),
                                race=hf and text(df.global.world.raws.creatures.all[hf.race].name[0])}
                        end
                        out.leads[#out.leads+1]=lead
                    end
                end
            end
            table.sort(out.leads,function(a,b)
                local x,y=a.site.distance or math.huge,b.site.distance or math.huge
                if x==y then return a.site.id<b.site.id end;return x<y
            end)
            out.leads_total=#out.leads;out.leads_truncated=#out.leads>limit
            while #out.leads>limit do table.remove(out.leads) end
        else out.leads_unavailable='Character rumor records are unavailable' end
    end
    return out
end

local function item_info(item,depth,budget,location,seen)
    depth=depth or 0; budget=budget or {remaining=300}; seen=seen or {}
    budget.remaining=budget.remaining-1
    local quality=item:getQuality()
    local out={id=item.id,description=text(dfhack.items.getReadableDescription(item)),
        quality=quality,wear=optional(function() return item:getWear() end),
        weight_raw=optional(function() return {whole=item.weight.whole,fraction=item.weight.fraction} end),
        weight_computed=optional(function() return item.flags.weight_computed end),location=location}
    for k,v in pairs(item_reader.storage(item))do out[k]=v end
    if budget.brief then
        local children=dfhack.items.getContainedItems(item)
        if #children>0 or (out.capacity_volume_raw or 0)>0 then out.contents_shown_in_full_view=#children end
        return out
    end
    out.type=df.item_type[item:getType()];out.subtype=item:getSubtype();out.stack_size=item:getStackSize()
    out.material=optional(function() return text(dfhack.matinfo.decode(item):toString()) end)
    out.material_ref=optional(function()
        local m=dfhack.matinfo.decode(item);return {type=m.type,index=m.index,token=m:getToken()}
    end)
    out.temperature=optional(function()return {whole=item.temperature.whole,fraction=item.temperature.fraction}end)
    out.volume_raw=optional(function() return item:getVolume() end)
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
            for index,a in ipairs(def.attacks) do
                out.weapon.attacks[#out.weapon.attacks+1]={attack_index=index,verb=text(a.verb_2nd),edged=a.edged,
                    contact=a.contact,penetration=a.penetration,velocity_mult=a.velocity_mult}
            end
        end
    end
    if seen[item.id] then out.contents_truncated=true; return out end
    seen[item.id]=true
    local children=dfhack.items.getContainedItems(item)
    -- A successfully read empty container is distinct from missing contents.
    -- Preserve the empty list for container postconditions and character state.
    if #children>0 or (out.capacity_volume_raw or 0)>0 then
        out.contents=array()
        for _,child in ipairs(children) do
            if depth>=(budget.max_depth or 4) or budget.remaining<=0 then
                out.contents_truncated=true;out.contents_total=#children;break
            end
            if budget.include_hidden or not child.flags.hidden then
                local child_location=copy(location or {});child_location.container_id=item.id
                child_location.mode=nil;child_location.body_part_id=nil
                out.contents[#out.contents+1]=item_info(child,depth+1,budget,child_location,seen)
            else
                out.contents_truncated=true;out.contents_total=#children
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
    local save_menu=saving.menu(ui)
    if save_menu then return save_menu end
    if rest.open() then return rest.menu() end
    if movement.open() then return movement.menu(ui) end
    local a=df.global.game.main_interface.adventure
    local m,kind,list
    if a.inventory.open then m=a.inventory;kind='inventory';list=m.option_current
    elseif a.option_list.open then m=a.option_list;kind='option_list';list=m.option
    else return nil end
    local out={kind=kind,context=m.context,
        context_name=optional(function()
            local enum=kind=='inventory' and df.adventure_interface_inventory_context_type
                or df.adventure_interface_option_list_context_type
            return enum[m.context]
        end),
        scroll=m.scroll_position,scrolling=m.scrolling,options=array(),total=#list,
        context_item_id=optional(function()return m.context_item.id end),
        context_position=optional(function()return pos(m.context_pos)end),
        started_from_main=optional(function()return m.started_from_main end),
        choosing_amount=optional(function()return m.doing_pickup_amount end),
        amount_index=optional(function()return m.pickup_amount_index end),
        amount_max=optional(function()return m.pickup_amount_max end),
        amount=optional(function()return m.number_amount end),
        entering_number=optional(function()return m.entering_number end),
        number=optional(function()return m.number_str end)}
    if out.scrolling then out.selection_unavailable='Finish dragging the list scroll bar before selection'
    elseif out.choosing_amount or out.entering_number then
        out.selection_unavailable='Finish the ground quantity choice before selection'
    end
    local drop_verified=bindings.support().native_hotkey_available
    for index,o in ipairs(list) do
        if #out.options>=500 then out.truncated=true;break end
        local name=bindings.named(o)
        local item=optional(function()return o:getItem()end) or optional(function()return o:getPickupItem()end)
        local container=optional(function()return o:getContainerItem()end)
        local action=df.adventure_option_type[o:getType()]
        local native_class=tostring(o):match('<([^:>]+)')
        local details=environment.option(o)
        for k,v in pairs(item_reader.option(o,action,drop_verified)) do details[k]=v end
        -- Some concrete option classes return type NONE and no item. Include
        -- native context, concrete class and full native label in their ID.
        local identity=json.encode({context=m.context,item_id=out.context_item_id,position=out.context_position,
            native_class=native_class,label=name,details=details},{pretty=false})
        local entry={index=index,id=('%s:%s:%d:%s:%s:%s'):format(kind,action,index,
                tostring(item and item.id),tostring(container and container.id),dfhack.internal.md5(identity)),
            label=name,kind=action,native_class=native_class,item_id=item and item.id,
            container_id=container and container.id,depth=o.depth}
        for k,v in pairs(details) do entry[k]=v end
        bindings.binding(entry,index,m.scroll_position,ui,
            (kind=='inventory' and bindings.inventory_supported(m.context)) or bindings.list_supported(out))
        out.options[#out.options+1]=entry
    end
    return bindings.catalog(bindings.text_menu(out,ui))
end

local interface_cache={}
local function interfaces(s,ui)
    local current=interface_cache[s]
    if not current then
        current={menu=menu_info(ui),conversation=interactions.conversation(ui),combat=interactions.combat(ui)}
        interface_cache[s]=current
    end
    return current
end
native_guard=function(s,ui)
    local out={complete=s.mode=='adventure' and s.screen=='viewscreen_dungeonmodest' and not s.interface_unavailable}
    if s.mode~='adventure' then return out end
    local current=interfaces(s,ui)
    local menu,conversation,combat=current.menu,current.conversation,current.combat
    -- Bindings and pixel coordinates are presentation/execution details. Native
    -- option identities, order, context, filters and cursor state are guards.
    local function guarded_menu(m)
        if not m then return nil end
        local g=copy(m);g.choices=nil
        for _,o in ipairs(g.options or {}) do o.click=nil;o.visible=nil;o.selection=nil;o.handle=nil end
        return g
    end
    out.menu=guarded_menu(menu)
    out.conversation=guarded_menu(conversation)
    out.combat=guarded_menu(combat)
    local known={inventory=menu and menu.kind=='inventory',option_list=menu and menu.kind=='option_list',
        ['main.options']=menu and menu.kind=='options' and not menu.selection_unavailable,
        sleep=menu and menu.kind=='rest' and not menu.selection_unavailable,
        movement_options=menu and menu.kind=='movement' and not menu.selection_unavailable,
        help=s.modal and s.modal.kind=='help' and type(s.modal.text)=='table',
        conversation=conversation.open and not conversation.selection_unavailable,
        attack=combat.open and not combat.selection_unavailable}
    for _,name in ipairs(s.open_panels) do if not known[name] then out.complete=false end end
    if (menu and menu.truncated) or conversation.truncated or combat.truncated then out.complete=false end
    local native_announcement=s.modal and s.modal.kind=='announcement' and s.modal.source=='native'
    if (s.modal and not known.help and not native_announcement)
        or (menu and (menu.choosing_amount or menu.entering_number)) then out.complete=false end
    if s.announcement_state and not s.announcement_state.available then out.complete=false end
    if #s.open_panels==0 then
        if s.adventure_menu~='Default' and s.adventure_menu~='Travel' then out.complete=false end
        if #s.focus~=1 or (s.focus[1]~='dungeonmode/Default' and s.focus[1]~='dungeonmode/Travel') then
            out.complete=false
        end
    end
    if not s.map_loaded then return out end
    local u=dfhack.world.getAdventurer()
    if u then
        out.character={id=u.id,position=pos(u.pos),blood=u.body.blood_count,wounds=#u.body.wounds,
            on_ground=u.flags1.on_ground,pain=u.counters.pain,unconscious=u.counters.unconscious,
            exhaustion=u.counters2.exhaustion,hunger=u.counters2.hunger_timer,
            thirst=u.counters2.thirst_timer,sleep=u.counters2.sleepiness_timer,inventory=array()}
        out.character.movement=movement.character(u)
        local seen={};local remaining=4096
        local function item_guard(item,depth)
            if seen[item.id] or remaining<=0 or depth>16 then out.complete=false;return {id=item.id,truncated=true} end
            seen[item.id]=true;remaining=remaining-1
            local g={id=item.id,type=item:getType(),stack=item:getStackSize(),wear=item:getWear(),
                in_inventory=item.flags.in_inventory,on_ground=item.flags.on_ground,contents=array()}
            for _,child in ipairs(dfhack.items.getContainedItems(item)) do
                if remaining<=0 then out.complete=false;g.truncated=true;break end
                g.contents[#g.contents+1]=item_guard(child,depth+1)
            end
            return g
        end
        for _,entry in ipairs(u.inventory) do
            if remaining<=0 then out.complete=false;break end
            local g=item_guard(entry.item,0);g.mode=entry.mode;g.body_part_id=entry.body_part_id
            out.character.inventory[#out.character.inventory+1]=g
        end
    end
    local visible=movement.visible_units(true,unit_info)
    for k,v in pairs(visible)do out[k]=v end
    if not visible.units_available or visible.units_truncated then out.complete=false end
    local reports=df.global.world.status.reports
    out.report_cursor=#reports>0 and reports[#reports-1].id or -1
    return out
end

local function character_base(u,full,brief)
    if not u then return nil end
    local out=unit_info(u)
    out.on_ground=u.flags1.on_ground
    if not brief then
    out.movement=movement.character(u)
    out.needs=character_calculations and character_calculations.brief_needs(u)
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
    end
    local budget={remaining=full and 4096 or 300,max_depth=full and 16 or 4,include_hidden=full,brief=brief}
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

local function adventurer_info(full) return character_base(dfhack.world.getAdventurer(),full) end

local function tile_info(x,y,z)
    local d,o=dfhack.maps.getTileFlags(x,y,z)
    if not d or not dfhack.maps.isTileVisible(x,y,z) then return {visible=false} end
    local tt=dfhack.maps.getTileType(x,y,z)
    local a=df.tiletype.attrs[tt]
    return {visible=true,type=df.tiletype[tt],shape=df.tiletype_shape[a.shape],
        material=df.tiletype_material[a.material],liquid_depth=d.flow_size,
        liquid=d.flow_size > 0 and (d.liquid_type and 'magma' or 'water') or nil,
        outside=d.outside,light=d.light,subterranean=d.subterranean,
        building=o.building ~= 0, dig=df.tile_dig_designation[d.dig]}
end

local shape_glyph={EMPTY=' ',FLOOR='.',BOULDER='o',PEBBLES='.',WALL='#',
    FORTIFICATION='#',STAIR_UP='<',STAIR_DOWN='>',STAIR_UPDOWN='X',RAMP='^',
    RAMP_TOP='v',BROOK_BED='~',BROOK_TOP='~',TREE='T',SAPLING='t',SHRUB='"',
    BRANCH='T',TRUNK_BRANCH='T',TWIG='t',ENDLESS_PIT='O'}

local function map_view(s,unit_target)
    local w=integer(req.width or 41,1,101,'width')
    local h=integer(req.height or 21,1,61,'height')
    local center=req.center or s.position or {x=df.global.window_x+w//2,y=df.global.window_y+h//2,z=df.global.window_z}
    local mx,my,mz=dfhack.maps.getTileSize()
    integer(center.x,0,mx-1,'center.x'); integer(center.y,0,my-1,'center.y'); integer(center.z,0,mz-1,'center.z')
    w=math.min(w,mx); h=math.min(h,my)
    local x0=math.max(0,math.min(mx-w,center.x-w//2))
    local y0=math.max(0,math.min(my-h,center.y-h//2))
    local z=center.z
    local target=unit_target and unit_target.position
    if req.route_target then
        target={}
        local reference=req.route_target.absolute or req.route_target.position
        check(type(reference)=='table','route_target requires position or absolute coordinates')
        for _,k in ipairs({'x','y','z'}) do
            target[k]=integer(reference[k],-2147483648,2147483647,'route_target.'..k)
                -(req.route_target.absolute and s.map_origin[k] or 0)
        end
    end
    local routing
    if target and s.position and target.z==s.position.z then
        routing=movement.route_window({x=mx,y=my},s.position,target,w,h)
        x0,y0,z,w,h=routing.origin.x,routing.origin.y,routing.origin.z,routing.width,routing.height
        routing.target=target
    end
    local cells,rows,walkable,liquids,visible={},array(),array(),array(),array()
    local landmarks=array()
    local buildings,liquid_tiles,seen_buildings=array(),array(),{}
    local buildings_truncated=false
    local buildings_unavailable_tiles=0
    for y=y0,y0+h-1 do
        cells[y]={};local walkrow,liquidrow,visrow={},{},{}
        for x=x0,x0+w-1 do
            local t=tile_info(x,y,z)
            if routing and target.x==x and target.y==y then routing.target_tile=t end
            visrow[#visrow+1]=t.visible and '1' or '0'
            if t.visible and t.building then
                local ok,b=pcall(dfhack.buildings.findAtTile,x,y,z)
                if not ok or not b then buildings_unavailable_tiles=buildings_unavailable_tiles+1;b=nil end
                if b and not seen_buildings[b.id] then
                    seen_buildings[b.id]=true
                    if #buildings<100 then buildings[#buildings+1]=environment.building(b)
                    else buildings_truncated=true end
                end
            end
            local liquid=t.visible and (t.liquid or (t.material=='FROZEN_LIQUID' and 'ice')
                or (t.shape=='BROOK_TOP' and 'brook'))
            if liquid then liquid_tiles[#liquid_tiles+1]={position={x=x,y=y,z=z},kind=liquid,depth=t.liquid_depth} end
            if t.visible and (t.shape:find('STAIR',1,true) or t.shape=='RAMP' or t.shape=='RAMP_TOP' or t.material=='CAMPFIRE') then
                landmarks[#landmarks+1]={position={x=x,y=y,z=z},shape=t.shape,type=t.type,material=t.material}
            end
            cells[y][x]=not t.visible and '?' or (t.liquid_depth > 0 and '~'
                or (t.material=='CAMPFIRE' and '*' or (t.building and 'B'
                    or (t.material=='TREE' and t.shape=='WALL' and 'T' or (shape_glyph[t.shape] or ':')))))
            local group=t.visible and dfhack.maps.getWalkableGroup({x=x,y=y,z=z}) or 0
            walkrow[#walkrow+1]=group and group>0 and '1' or '0'
            liquidrow[#liquidrow+1]=t.visible and tostring(t.liquid_depth or 0) or '?'
        end
        walkable[#walkable+1]=table.concat(walkrow);liquids[#liquids+1]=table.concat(liquidrow)
        visible[#visible+1]=table.concat(visrow)
    end
    local native=guard_cache[s]
    local nearby=movement.map_units(native.units or {},{x=x0,y=y0,z=z},w,h,s.adventurer_id)
    for _,info in ipairs(nearby) do
        if info.in_map then cells[info.position.y][info.position.x]=info.glyph end
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
        origin={x=x0,y=y0,z=z},width=w,height=h,rows=rows,units=nearby,walkable=walkable,visible=visible,liquid_depths=liquids,landmarks=landmarks,
        units_scope='All loaded visible units, including outside this ASCII crop and z-level',
        units_truncated=native.units_truncated or false,units_available=native.units_available,
        units_unavailable=native.units_unavailable,routing_window=routing,
        buildings=buildings,buildings_truncated=buildings_truncated,buildings_unavailable_tiles=buildings_unavailable_tiles,
        liquid_regions=environment.liquids(liquid_tiles,s.position or center),feature_distance_from=s.position or center,
        legend={['@']='adventurer',u='visible creature (see units)',B='building',['*']='campfire',
            ['#']='wall/fortification',['.']='floor',['~']='liquid/brook',T='tree',
            ['<']='up stair',['>']='down stair',X='up/down stair',['^']='ramp',
            ['?']='unseen/unavailable',[' ']='open space',[':']='other terrain',
            o='boulder',t='sapling/twig',v='ramp top',O='endless pit',['"']='shrub'},
        visibility='DFHack isTileVisible plus isHidden for units; not a strict UI-only information boundary'}
end

local function observe(ui,s,pending_only)
    ui=ui or ui_rows()
    s=s or status(ui)
    local record=session.dispatches[req.dispatch_id or req.parent_dispatch or '']
    local replaced=record and not lifetime.matches(record,session)
    -- Do this before state_id: a full native guard traverses inventories and
    -- active menus. Neither is needed or safe to reuse as a processing sample.
    if pending_only then return progress_reader(s,req,replaced) end
    local out={status=s,ui=ui,state_id=state_id(s,ui),effect_id=state_id(s,ui,true),
        input_guard={schema=2,native_complete=guard_cache[s].complete}}
    if req.watch_units then out.watched_units=health.read(req.watch_units,s.mode=='adventure' and s.map_loaded) end
    if req.strike_state then out.strike_state=attack.state() end
    if req.input_evidence_for then
        local receipt=session.receipts[req.input_evidence_for]
        local evidence=receipt and receipt.evidence
        out.input_evidence=evidence and evidence.world_epoch==session.world_epoch and copy(evidence)
            or {available=false,reason='Input evidence is unavailable in this world'}
    end
    local function finish_observation()
        if ui.captured then out.ui_state_id=state_id(s,ui,false,true) end
        -- Lazy readers must never enter persisted snapshots. Retain only the
        -- materialized JSON fields, including the explicit omission marker.
        setmetatable(ui,nil)
        return out
    end
    if req.scope=='choices' then
        if s.mode=='adventure' then
            local current=interfaces(s,ui)
            out.menu=current.menu
            local c,combat=current.conversation,current.combat
            if c.open then out.conversation=c end
            if combat.open then out.combat=combat end
        end
        return finish_observation()
    end
    if s.mode=='adventure' then
        out.navigation=navigation_info(s,false)
        if req.rest_state then out.rest=rest.state(s) end
        if req.save_name then out.save_file=saving.file(req.save_name) end
        -- Report history belongs to the world, not the loaded local map.
        -- Preserve its cursor during travel so returning cannot replay history.
        for k,v in pairs(read_reports(df.global.world.status.reports,req.reports_after,req.report_limit,replaced)) do out[k]=v end
    end
    if s.map_loaded and s.mode=='adventure' then
        local target_id=req.target_unit_id or (req.action and req.action.unit_id)
        local target=target_id and df.unit.find(integer(target_id,0,2147483647,'unit_id'))
        if target and dfhack.units.isVisible(target) and not dfhack.units.isHidden(target) then
            out.target_unit=unit_info(target)
            local unconscious=optional(function()return target.counters.unconscious end)
            if type(unconscious)=='number' then out.target_unit.health={unconscious=unconscious}
            else out.target_unit.health_unavailable='Native unconsciousness counter is unavailable' end
            if req.strike_state then out.target_unit.condition=health.condition(target)end
        end
        out.adventurer=adventurer_info()
        if req.receipt_state then out.adventurer.burden=burden.read(dfhack.world.getAdventurer()).burden end
        if req.character_progress then
            out.adventurer.progress=character_reader(dfhack.world.getAdventurer(),{},
                {array=array,text=text,profile='progress'})
        end
        out.nearby_items,out.nearby_items_truncated=nearby_items(s,req.radius)
        out.menu=interfaces(s,ui).menu
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
        if req.map ~= false then out.map=map_view(s,out.target_unit) end
        if interactions then
            local current=interfaces(s,ui)
            local c,combat=current.conversation,current.combat
            if c.open then out.conversation=c end
            if combat.open then out.combat=combat end
            if req.conversation_activity then
                local ref=req.conversation_activity
                out.conversation_activity=interactions.activity(
                    integer(ref.activity_id,0,2147483647,'activity_id'),
                    integer(ref.activity_event_id,0,2147483647,'activity_event_id'))
            end
        end
    end
    return finish_observation()
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

local function guard_state(expected,actual,view)
    if expected and expected~=actual then
        view=view or observe()
        local details={expected=expected,actual=actual,view=view}
        local record=req.parent_dispatch and session.dispatches[req.parent_dispatch]
        if record then
            local snapshot=wire.observe(record,req.parent_dispatch,view)
            details.view_ref=snapshot.view_ref
        end
        error({message='State changed before input; review the returned observation.',code='stale_state',
            input_sent=false,details=details},0)
    end
end

local function act()
    check(type(req.request_id)=='string' and #req.request_id<=100,'request_id is required')
    local previous=session.receipts[req.request_id]
    if previous then
        check(previous.request==json.encode(req,{pretty=false}),'request_id reused with different arguments')
        return {action_id=req.request_id,duplicate=true,dispatch=previous.dispatch,
            workflow_revision=previous.workflow_revision}
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
    guard_state(req.expect,state_id(s,ui,false,req.expect and req.expect:sub(1,3)=='u2:'))
    if req.watch_units then
        local current=health.read(req.watch_units,s.mode=='adventure' and s.map_loaded)
        if not health.matches(req.watch_expect,current) then
            error({message='Watched unit health changed before input; review the returned observation.',
                code='watch_changed',input_sent=false,details={view=observe(ui,s)}},0)
        end
    end
    if a.type=='dismiss' then
        check(s.modal and s.modal.dismissible,'No supported help or announcement prompt to dismiss')
        local response_key=runtime.acknowledgement_key(s.modal)
        a=response_key and {type='key',key=response_key} or {type='click_text',text=s.modal.button}
    end
    local key=a.key
    local scroll_menu,scroll_option
    local native_menu,native_option
    if a.type=='move' or a.type=='wait' then
        check(s.mode=='adventure' and s.screen=='viewscreen_dungeonmodest', 'Movement requires an active local adventure')
        check(s.can_move, 'Close the current menu before moving or waiting')
        if a.type=='move' then
            check(type(a.direction)=='string' and directions[a.direction:lower()],'Invalid movement direction')
            key='A_MOVE_'..directions[a.direction:lower()]
        else key='A_SHORT_WAIT' end
    elseif a.type=='key' then
        check(type(key)=='string','key must be an interface_key name')
    elseif a.type=='select_option' or (a.type=='scroll_menu' and a.menu_kind~='conversation') then
        check(not s.modal,'Handle the current prompt before selecting an option')
        local menu=menu_info(ui);local found
        if menu then for _,o in ipairs(menu.options)do if o.id==a.option_id or o.handle==a.option_id then found=o;break end end end
        check(found,'Native option is absent; observe before selecting')
        check(not menu.selection_unavailable,menu.selection_unavailable or 'Native menu selection is unavailable')
        check(not menu.choosing_amount and not menu.entering_number,'Finish the native quantity choice before selecting another option')
        if a.type=='scroll_menu' then
            check(menu.kind==a.menu_kind,'Menu changed before scroll')
            scroll_menu,scroll_option=menu,found
        elseif found.selection then
            native_menu,native_option=menu,found
        else
            check(found.visible and found.click,'Option has no verified input binding; inspect the returned choices')
            a={type='click',x=found.click.x,y=found.click.y,button='left'}
        end
    elseif a.type=='select_interaction' or a.type=='scroll_menu' then
        check(not s.modal and interactions,'Handle the current modal before selecting an interaction')
        local option,menu=interactions.option(a.option_id,ui)
        check(option and not menu.selection_unavailable,'Interaction option has no verified binding; inspect the returned choices')
        if a.type=='scroll_menu' then
            check(menu.kind==a.menu_kind,'Menu changed before scroll')
            scroll_menu,scroll_option=menu,option
        elseif option.selection then
            native_menu,native_option=menu,option
        else
            check(option.visible and option.click,'Interaction option has no verified visible binding; inspect the returned choices')
            a={type='click',x=option.click.x,y=option.click.y,button='left'}
        end
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
    elseif a.type=='edit_text' then
        check(a.field=='save_name','Unknown native text field')
        saving.validate_name(a.value)
        local current=saving.menu(ui)
        check(current and current.mode=='filename' and not current.selection_unavailable,
            'No verified native save-name field is active')
    elseif a.type=='text' then
        check(type(a.text)=='string' and #a.text>0 and #a.text<=200,'text must be 1..200 ASCII bytes')
        check(not a.text:find('[^ -~]'),'text only accepts printable ASCII; use key for Enter/Escape')
    else error('Unknown action type: '..tostring(a.type),0) end
    if key then check(df.interface_key[key]~=nil,'Unknown interface_key: '..tostring(key)) end
    local evidence
    if req.capture then
        local ok,value=pcall(attack.prepare,req.capture,native_menu,native_option)
        if not ok then error({message=tostring(value),code='capture_unavailable',input_sent=false,
            details={view=observe(ui,s)}},0) end
        evidence=value
    end
    -- Register before input: an input failure can have partial effects and must not be retried blindly.
    local receipt={request=json.encode(req,{pretty=false}),settled=false,evidence=evidence}
    local before_effect_id=state_id(s,ui,true)
    local reports=s.map_loaded and df.global.world.status.reports
    local report_id=reports and #reports>0 and reports[#reports-1].id or -1
    if req.parent_dispatch then
        local parent=session.dispatches[req.parent_dispatch]
        check(parent and lifetime.matches(parent,session),'World changed; start a new dispatch after observing')
        check(parent and session.active_dispatch==req.parent_dispatch,'Dispatch is no longer active')
        if parent.interrupted then return {interrupted=true,action_id=req.request_id} end
        parent.workflow=wire.checkpoint(parent,req)
        parent.workflow_revision=(parent.workflow_revision or 0)+1
        receipt.workflow_revision=parent.workflow_revision
        parent.last_action_id=req.request_id
    end
    session.receipts[req.request_id]=receipt
    session.order[#session.order+1]=req.request_id
    if #session.order>128 then session.receipts[table.remove(session.order,1)]=nil end
    session.pending=req.request_id
    session.serial=session.serial+1
    input_registered=true
    local ok,err=xpcall(function()
        if native_menu then
            -- Probe native scroll bounds, then resolve the input from fresh
            -- native options. Topic offsets are lines; uniform lists use indices.
            receipt.ui_adjustment=bindings.prepare(native_menu,native_option)
            local current
            if native_menu.kind=='conversation' then current=interactions.conversation(ui)
            elseif native_menu.kind=='combat' then current=interactions.combat(ui)
            else current=menu_info(ui) end
            local found
            for _,o in ipairs(current and current.options or {}) do
                if o.id==native_option.id then check(not found,'Native option became ambiguous');found=o end
            end
            check(found and found.index==native_option.index and not current.selection_unavailable,
                'Native menu target changed during UI normalization; no selection key was sent')
            check(df.global.world.frame_counter==s.world_frame and not status(ui).modal,
                'Game state changed during UI normalization; no selection key was sent')
            key=bindings.selection_key(current,found)
            gui.simulateInput(dfhack.gui.getCurViewscreen(true),key)
        elseif scroll_menu then receipt.ui_adjustment=bindings.scroll(scroll_menu,scroll_option)
        elseif key then gui.simulateInput(dfhack.gui.getCurViewscreen(true),key)
        elseif a.type=='click' then click(a.x,a.y,a.button or 'left')
        elseif a.type=='edit_text' then
            receipt.ui_adjustment={field=a.field,native_key_inputs=saving.edit(a.value,ui)}
        elseif a.type=='resume' then -- no input
        else
            for i=1,#a.text do
                gui.simulateInput(dfhack.gui.getCurViewscreen(true),('STRING_A%03d'):format(a.text:byte(i)))
            end
        end
        if evidence then attack.submitted(evidence,session,receipt,req.request_id) end
    end,debug.traceback)
    receipt.error=not ok and tostring(err) or nil
    if s.travel and s.travel.active and key and key:match('^A_MOVE_') then
        -- Overland input advances up to three travel tiles asynchronously while
        -- player_control_state remains TAKING_INPUT. UI frames alone are not a
        -- completion signal. Require an unchanged native travel state for a
        -- short quiet window; the recipe still verifies the requested result.
        local started=dfhack.getTickCount()
        local epoch=session.world_epoch
        local changed=started
        local previous_signature
        local function settle_travel()
            if session.world_epoch~=epoch or not dfhack.isWorldLoaded() then
                receipt.error='World changed while input was settling; no input was repeated'
                receipt.settled=true;return
            end
            local now=dfhack.getTickCount()
            local travel_state=df.global.adventure
            local signature=json.encode({travel=travel_info(),offload=travel_state.offload_timer,
                long_action=travel_state.long_action_duration,phase=travel_state.player_control_state},{pretty=false})
            if signature~=previous_signature then previous_signature=signature;changed=now end
            if now-changed>=250 then receipt.settled=true
            elseif now-started>=30000 then
                receipt.error='Travel state did not settle within 30 seconds; no input was repeated'
                receipt.settled=true
            else dfhack.timeout(1,'frames',settle_travel) end
        end
        dfhack.timeout(2,'frames',settle_travel)
    else dfhack.timeout(2,'frames',function() receipt.settled=true end) end
    return {action_id=req.request_id,accepted=ok,error=receipt.error,
        workflow_revision=receipt.workflow_revision,
        input_key=key,ui_adjustment=receipt.ui_adjustment,
        before_effect_id=before_effect_id,before_report_id=report_id}
end

local function dispatch()
    check(type(req)=='table','Request must be an object')
    if req.op=='capabilities' then return runtime.capabilities()
    elseif req.op=='status' then return status()
    elseif req.op=='unit' then
        local id=integer(req.unit_id,0,2147483647,'unit_id')
        local ui=ui_rows();local s=status(ui)
        local out={format='unit_status',status=s,state_id=state_id(s,ui),available=false,unit_id=id}
        local u=s.map_loaded and df.unit.find(id)
        if not u or not dfhack.units.isVisible(u) or dfhack.units.isHidden(u) then
            out.reason='Unit is not currently loaded and visible';return out
        end
        check(type(unit_reader)=='function','Unit reader was not supplied by this client')
        out.unit=unit_reader(u,character_base(u,true),{array=array,text=text})
        out.available=true;return out
    elseif req.op=='navigation' then
        local ui=ui_rows();local s=status(ui)
        check(s.mode=='adventure','Navigation requires an active adventure')
        return {status=s,state_id=state_id(s,ui),navigation=navigation_info(s,true)}
    elseif req.op=='character_status' or req.op=='character_brief' then
        local brief=req.op=='character_brief'
        local ui=ui_rows();local s=status(ui)
        local result={schema_version=2,format=brief and 'character_brief' or 'character_status',status=s,
            state_id=state_id(s,ui),effect_id=state_id(s,ui,true),available=false}
        local u=s.mode=='adventure' and dfhack.world.getAdventurer()
        if not u then result.reason='No active adventurer is available';return result end
        check(type(character_reader)=='function','Character reader was not supplied by this client')
        check(type(character_details)=='function','Character details reader was not supplied by this client')
        check(type(character_calculations)=='table','Character calculations were not supplied by this client')
        result.character=character_reader(u,character_base(u,true,brief),{array=array,text=text,ui=ui,status=s,
            interfaces=interfaces(s,ui),next_dawn=not brief and rest.dawn(s) or nil,
            details_reader=character_details,calculations=character_calculations,burden=burden,
            profile=brief and 'brief' or nil})
        result.available=true
        return result
    elseif req.op=='observe' then return observe()
    elseif req.op=='act' then return act()
    elseif req.op=='begin_dispatch' then
        check(type(req.request_id)=='string' and #req.request_id>0 and #req.request_id<=100,'Invalid request_id')
        local previous=session.dispatches[req.request_id]
        local signature=wire.intent(req)
        if previous then
            check(wire.intent(previous.request)==signature,'request_id reused with different arguments')
            if req.result_format=='compact' and previous.compact then
                return {duplicate=true,compact=previous.compact}
            end
            return {duplicate=true,dispatch=not previous.view and previous.dispatch or nil,
                view=previous.view or observe(),action_id=req.request_id,compact=previous.compact}
        end
        local view=observe()
        guard_state(req.expect,req.expect and req.expect:sub(1,3)=='u2:' and view.ui_state_id or view.state_id,view)
        local workflow={action=req.action,context=require('json.internal'):newObject{}}
        local resume_id=req.action and req.action.type=='resume' and req.action.dispatch_id
        local last_action_id
        if resume_id then
            local prior=session.dispatches[resume_id]
            check(prior,'Unknown dispatch (game restarted or receipt expired)')
            check(not prior.resumed_by,'Dispatch was already resumed; use its latest continuation')
            local resume_reason=lifetime.resume_reason(prior,session,view.status)
            check(not resume_reason,resume_reason)
            check(not session.active_dispatch or session.active_dispatch==resume_id,'Another dispatch is active')
            workflow=copy(prior.workflow);last_action_id=prior.last_action_id
        else
            local active=session.active_dispatch and session.dispatches[session.active_dispatch]
            check(not active or active.interrupted,'Another dispatch is active; interrupt or resume it first')
        end
        local record={request=signature,workflow=workflow,save=view.status.save,world_epoch=session.world_epoch,
            adventurer_id=view.status.adventurer_id,last_action_id=last_action_id,
            interrupted=session.interrupt_requests[req.request_id] or false}
        session.interrupt_requests[req.request_id]=nil
        session.dispatches[req.request_id]=record
        if resume_id then session.dispatches[resume_id].resumed_by=req.request_id end
        session.dispatch_order[#session.dispatch_order+1]=req.request_id
        if #session.dispatch_order>128 then session.dispatches[table.remove(session.dispatch_order,1)]=nil end
        session.active_dispatch=req.request_id
        record.workflow_revision=0
        local response=wire.observe(record,req.request_id,view)
        response.action_id=req.request_id;response.workflow=workflow;response.last_action_id=last_action_id
        response.workflow_revision=0
        local receipt=session.receipts[last_action_id or session.pending]
        response.ready=view.status.ready_for_input and (not receipt or receipt.settled)
        response.interrupted=record.interrupted
        response.action_error=receipt and receipt.error
        return response
    elseif req.op=='finish_dispatch' then
        local record=session.dispatches[req.action_id]
        check(record,'Unknown dispatch')
        local final_view=wire.receipt_view(record,req.action_id,req)
        local final_workflow=wire.checkpoint(record,req)
        local summary=copy(req.dispatch)
        if req.dispatch_from_workflow then
            summary.action=copy(final_workflow.action)
            summary.events=copy(final_workflow.events or array())
            summary.prompts=copy(final_workflow.prompts or array())
            summary.results=copy(final_workflow.context.results)
        end
        if final_view then
            final_view.status.active_dispatch=nil
            final_view.dispatch=summary;final_view.action={action_id=req.action_id}
        end
        record.dispatch=summary;record.workflow=final_workflow
        record.workflow_revision=(record.workflow_revision or 0)+1
        record.view=final_view;record.compact=req.compact and copy(req.compact)
        record.snapshot=nil
        if session.active_dispatch==req.action_id then session.active_dispatch=nil end
        return {recorded=true,workflow_revision=record.workflow_revision}
    elseif req.op=='dispatch_details' then
        check(type(req.dispatch_id)=='string' and #req.dispatch_id>0,'dispatch_id must be nonempty')
        local section=req.section or 'events'
        check(section=='events' or section=='prompts' or section=='steps' or section=='summary'
            or section=='full' or section=='compact','Unknown dispatch detail section')
        local record=session.dispatches[req.dispatch_id]
        if not record then return {available=false,dispatch_id=req.dispatch_id,
            reason='Unknown or expired dispatch; the native session retains the last 128 dispatches'} end
        if not record.dispatch then return {available=false,dispatch_id=req.dispatch_id,
            reason='Dispatch has no final receipt yet; execution is not affected by this query'} end
        local value=section=='summary' and record.dispatch or section=='full' and record.view
            or section=='compact' and record.compact or record.dispatch[section]
        if section=='full' and not value then value={dispatch=record.dispatch,observation_unavailable=true} end
        return {available=value~=nil,dispatch_id=req.dispatch_id,section=section,value=value}
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
        local ui=ui_rows();local s=status(ui)
        local receipt=session.receipts[req.action_id or session.pending]
        check(not req.action_id or receipt,'Unknown action receipt (game restarted or receipt expired)')
        local running=req.dispatch_id and session.dispatches[req.dispatch_id]
        local response={ready=s.ready_for_input and (not receipt or receipt.settled),status=not req.observe and s or nil,
            interrupted=running and (running.interrupted or session.active_dispatch~=req.dispatch_id) or false,
            action_error=receipt and receipt.error,
            world_changed=running and not lifetime.matches(running,session) or nil}
        if req.observe and req.pending_reads and req.ui_mode~='full' and not response.ready
            and not response.interrupted and not response.action_error and not response.world_changed then
            response.pending_view=observe(ui,s,true)
            return response
        end
        local view=req.observe and observe(ui,s)
        if view then
            if running then
                for k,v in pairs(wire.observe(running,req.dispatch_id,view,req.view_ref))do response[k]=v end
            else response.view=view end
        end
        return response
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
            if out.building then
                local ok,b=pcall(dfhack.buildings.findAtTile,x,y,z)
                out.building_info=ok and b and environment.building(b) or
                    {available=false,reason='Native building lookup is unavailable for this occupied tile'}
            end
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

local ok,result=xpcall(dispatch,function(err)
    if type(err)=='table' and err.code then return err end
    return {message=tostring(err):match('^[^\n]+'),code='bridge_error',debug=debug.traceback(tostring(err),2)}
end)
if not ok and req.op=='act' and not input_registered and not result.details then
    local observed,view=pcall(observe)
    result.code='input_rejected';result.input_sent=false
    if observed then result.details={view=view} end
end
if not ok and req.op=='begin_dispatch' then
    result.details=result.details or {}
    result.details.dispatch_registered=session.dispatches[req.request_id]~=nil
    if not result.details.dispatch_registered then result.input_sent=false end
end
return ok and {ok=true,result=result} or {ok=false,error=result.message,code=result.code,
    input_sent=result.input_sent,details=result.details,debug=result.debug}

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
