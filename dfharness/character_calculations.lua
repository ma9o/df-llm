--@ module=true
--luacheck: globals factory
local function build()
-- Read-only DF 53.16 Windows calculations, reconstructed from the installed
-- executable. See docs/character-calculations.md for provenance and limits.
-- No native movement/weight calculation is called: those can mutate caches,
-- consume randomness, or train attributes. The numerical models use plain data.
local M={}
local floor,min,max=math.floor,math.min,math.max
local function integer(n,lo,hi)
    assert(type(n)=='number' and n==floor(n) and n>=lo and n<=hi,'Missing or out-of-range calculation input')
    return n
end
local function trunc(n) return n<0 and math.ceil(n) or floor(n) end
local function i32(n) return integer(n,-2147483648,2147483647) end
local function mul(a,b) return i32(a*b) end
local function add(a,b) return i32(a+b) end
local function clamp(n,lo,hi) return max(lo,min(hi,n)) end
local function array() return require('json.internal'):newArray{} end

M.build={df_version='53.16',runtime_version='v0.53.16 win64 STEAM',os='windows',pe_timestamp=1785767641,
    source='Installed DF executable; pure read-only reconstruction',
    model='df53.16-win-character-v2'}
function M.supported(version,os,pe)
    return version==M.build.runtime_version and os==M.build.os and pe==M.build.pe_timestamp
end
local stages={
    hunger={{57600,'Hungry'},{172800,'Hungry'},{1209600,'Very hungry'},{2592000,'Starving'}},
    thirst={{57600,'Thirsty'},{115200,'Thirsty'},{172800,'Very thirsty'},{345600,'Dehydrated'}},
    sleep={{115200,'Drowsy'},{172800,'Drowsy'},{259200,'Drowsy'},{345600,'Very drowsy'},{864000,'Slumberous'}},
    blood_thirst={{172800,'Thirsty'},{1209600,'Thirsty'},{2419200,'Thirsty!'}},
}
function M.need(kind,counter,required)
    i32(counter)
    assert(type(required)=='boolean','Physiological requirement is unknown')
    local result={available=true,counter=counter,required=required,units='native_counter',
        severity=0,label='No warning',state='none'}
    if not required then result.state='exempt';result.label='Not required';return result end
    for index,stage in ipairs(assert(stages[kind])) do
        if counter>=stage[1] then
            result.severity=index;result.label=stage[2];result.native_label=stage[2]
            result.stage_start=stage[1];result.state='warning'
        else
            result.next_stage={severity=index,label=stage[2],counter=stage[1],remaining_counter=stage[1]-counter}
            break
        end
    end
    return result
end

function M.brief_needs(u)
    local ok,result=pcall(function()
        assert(M.supported(dfhack.getDFVersion(),dfhack.getOSType(),dfhack.internal.getPE()),
            'No verified need calculation for this executable')
        local caste=df.global.world.raws.creatures.all[u.race].caste[u.caste]
        local out={}
        for _,v in ipairs({{'hunger','hunger_timer','NO_EAT'}, {'thirst','thirst_timer','NO_DRINK'},
                {'sleep','sleepiness_timer','NO_SLEEP'}}) do
            local base=caste.flags[v[3]]
            local added=u.uwss_add_caste_flag[v[3]]
            local removed=u.uwss_remove_caste_flag[v[3]]
            assert(type(base)=='boolean' and type(added)=='boolean' and type(removed)=='boolean',
                'Creature requirement is unavailable')
            local n=M.need(v[1],u.counters2[v[2]],not (not removed and (base or added)))
            out[v[1]]={severity=n.severity,label=n.label,required=n.required}
        end
        return out
    end)
    return ok and result or {available=false,reason=tostring(result)}
end

-- Current native skill penalties (including the corrected 864000 sleep
-- threshold). Only movement-relevant skills are interpreted here.
function M.skill(nominal,s)
    local r=integer(nominal,0,2147483647)
    local c,c2=s.counters,s.counters2
    if c.soldier_mood==-1 then
        for _,v in ipairs({c.nausea,c.winded,c.stunned,c.dizziness,c2.fever}) do
            if v>0 then r=floor(r/2) end
        end
    end
    if not s.vision then r=floor(r/4) end
    if c.soldier_mood~=0 then
        if c.pain>=100 and s.mood==-1 then r=floor(r/2) end
        for _,threshold in ipairs({2000,4000,6000}) do
            if c2.exhaustion>=threshold then r=trunc(mul(r,3)/4) end
        end
    end
    if s.bloodsucker then
        if s.blood_timer>=2419200 then r=floor(r/2)
        elseif s.blood_timer>=1209600 then r=trunc(mul(r,3)/4) end
    end
    local function need_penalty(counter,a,b,highest)
        if counter>=highest then r=floor(r/2)
        elseif counter>=b then r=trunc(mul(r,3)/4)
        elseif counter>=a then r=trunc(mul(r,9)/10) end
    end
    need_penalty(c2.thirst_timer,115200,172800,345600)
    need_penalty(c2.hunger_timer,172800,1209600,2592000)
    if c2.sleepiness_timer>=864000 then r=floor(r/4)
    else need_penalty(c2.sleepiness_timer,172800,259200,345600) end
    return r
end

function M.movement(s,load_cost,buildup)
    local g=s.gait
    local cost=g.full_speed
    if buildup and g.buildup_time>0 and s.buildup<g.buildup_time then
        cost=trunc(add(mul(g.buildup_time-s.buildup,g.start_speed),mul(s.buildup,g.full_speed))/g.buildup_time)
    end
    local components=array()
    local function set(name,value)
        i32(value)
        if value~=cost then components[#components+1]={source=name,before=cost,after=value} end
        cost=value
    end
    if s.turbospeed then return 0,components end
    if s.ghost then return cost,components end
    local c,c2=s.counters,s.counters2
    if s.speed_percent~=100 then
        local v=mul(cost,100)
        if s.speed_percent>0 then v=trunc(v/s.speed_percent) end
        set('curse_speed_percent',v)
    end
    set('curse_speed_add',add(cost,s.speed_add))
    if s.swimming then
        if s.swimming_skill>1 then set('swimming_skill',trunc(mul(cost,max(6,21-s.swimming_skill))/20)) end
    elseif s.liquid_type==0 or s.liquid_type==2097152 then
        set('liquid_depth',add(cost,mul(s.liquid_depth,s.liquid_type==0 and 150 or 300)))
    end
    if s.baby then set('baby',add(cost,3000)) end
    if s.diving then set('diving',trunc(cost/20)) end
    for _,threshold in ipairs({2000,4000,6000}) do
        if c2.exhaustion>=threshold then set('exhaustion_'..threshold,add(cost,200)) end
    end
    if s.gutted then set('gutted',add(cost,2000)) end
    if c.soldier_mood==-1 then
        for _,name in ipairs({'nausea','winded','stunned','dizziness'}) do
            if c[name]>0 then set(name,add(cost,1000)) end
        end
        if c2.fever>0 then set('fever',add(cost,1000)) end
    end
    if c.pain>=100 and c.soldier_mood~=0 and s.mood==-1 then set('pain',add(cost,1000)) end
    if s.bloodsucker then
        if s.blood_timer>=2419200 then set('blood_thirst',add(cost,200))
        elseif s.blood_timer>=1209600 then set('blood_thirst',add(cost,100)) end
    end
    local function need_cost(name,counter,thresholds)
        for _,v in ipairs(thresholds) do
            if counter>=v[1] then set(name,add(cost,v[2]));return end
        end
    end
    need_cost('thirst',c2.thirst_timer,{{345600,200},{172800,100}})
    need_cost('hunger',c2.hunger_timer,{{2592000,200},{1209600,100}})
    need_cost('sleep',c2.sleepiness_timer,{{864000,200},{345600,100},{259200,75},{172800,50}})
    if s.dragging then set('dragging',add(cost,1000)) end
    if s.mode=='WALK' and s.on_crutch then set('crutch',add(cost,2000-mul(min(20,s.crutch_skill),100))) end
    if c2.paralysis>=1 and c2.paralysis<=99 then set('paralysis',add(cost,mul(c2.paralysis,10))) end
    if c.webbed>=1 and c.webbed<=9 then set('webbed',add(cost,mul(c.webbed,100))) end
    local low,high,total=0,0,0
    for _,a in ipairs({{'strength',s.strength},{'agility',s.agility}}) do
        if g.flags[a[1]] then low=low+100;high=high+1900;total=total+min(1900,a[2]) end
    end
    if g.flags.layers_slow then
        local size_factor=1000
        if s.size_cur~=s.size_base and s.size_cur~=0 then
            -- Native uses int64 for size_base > 100000, int32 otherwise.
            local product=s.size_base>100000 and s.size_base*1000 or mul(s.size_base,1000)
            size_factor=clamp(trunc(product/s.size_cur),100,1900)
        end
        low=low+100;high=high+1900;total=total+size_factor
    end
    if low>0 then
        total=clamp(total,low,high)
        local slow=trunc(mul(cost,4)/3)
        local fast=floor(cost/2)
        set('gait_attributes_and_size',trunc(add(mul(high-total,slow),mul(total-low,fast))/(high-low)))
    end
    if s.sneaking and g.stealth_slows>0 then set('stealth',add(cost,trunc(mul(cost,g.stealth_slows)/100))) end
    if not s.on_ground and s.stand_max>=3 then
        local missing=s.stand_max-s.stand_count-(s.on_crutch and 1 or 0)
        local v=trunc(mul(missing,500)/(s.stand_max-floor(s.stand_max/2)-1))
        if v>0 then set('missing_stance_parts',add(cost,v)) end
    end
    if s.mood==5 then set('melancholy',add(cost,8000)) end
    set('carried_load',add(cost,load_cost))
    set('native_clamp',clamp(cost,0,9999))
    return cost,components
end

function M.speed(cost)
    assert(cost+100>0,'Native movement denominator is not positive')
    local displayed=floor(1000000/(cost+100))/1000
    return {value=1000/(cost+100),displayed_value=displayed,displayed_text=string.format('%.3f',displayed),
        movement_cost=cost,movement_delay=cost+100}
end

function M.apply(u,out,h)
    local function read(path,fn)
        return h.read(path,fn) or {available=false,reason='Calculation could not be verified; see unavailable'}
    end
    local verified,why=pcall(function()
        assert(M.supported(dfhack.getDFVersion(),dfhack.getOSType(),dfhack.internal.getPE()),
            'No verified character calculation for this executable build')
        assert(df.global.gamemode==df.game_mode.ADVENTURE,'Character calculations require Adventure mode')
    end)
    local function check_build() assert(verified,tostring(why)) end
    out.physiology.interpreted_needs=read('physiology.interpreted_needs',function()
        check_build()
        local f=assert(out.physiology.effective_creature_flags,'Creature requirements are unreadable')
        local result={available=true,source=M.build,semantics='Native warning stages; severity is their order, not controller risk. No warning means below the first threshold, not a fullness measurement.'}
        for _,v in ipairs({{'hunger','hunger_timer','NO_EAT','debug_noeat'},
                {'thirst','thirst_timer','NO_DRINK','debug_nodrink'},{'sleep','sleepiness_timer','NO_SLEEP','debug_nosleep'}}) do
            assert(type(f[v[3]])=='boolean','Creature exemption is unknown')
            result[v[1]]=M.need(v[1],u.counters2[v[2]],not f[v[3]])
            result[v[1]].exemption_flag=v[3]
            result[v[1]].debug_timer_disabled=df.global[v[4]]
        end
        if f.BLOODSUCKER then
            local trait=dfhack.units.getMiscTrait(u,df.misc_trait_type.TimeSinceSuckedBlood,false)
            result.blood_thirst=M.need('blood_thirst',trait and trait.value or 0,true)
        end
        return result
    end)

    -- Read only mapped, cached fields. A stale native body cache is unknown;
    -- native update-body/weight helpers are deliberately never invoked.
    local state_ok,s=pcall(function()
        check_build()
        assert(u.flags2.calculated_bodyparts,'Native body-part cache requires refresh')
        local function flag(name)
            local v=h.caste.flags[name]
            local ok,added=pcall(function() return u.uwss_add_caste_flag[name] end)
            local ok2,removed=pcall(function() return u.uwss_remove_caste_flag[name] end)
            return not (ok2 and removed) and ((ok and added) or v) or false
        end
        local c,c2={},{}
        for _,name in ipairs({'soldier_mood','nausea','winded','stunned','dizziness','pain','webbed','unconscious'}) do c[name]=i32(u.counters[name]) end
        for _,name in ipairs({'fever','exhaustion','hunger_timer','thirst_timer','sleepiness_timer','paralysis'}) do c2[name]=i32(u.counters2[name]) end
        local r={counters=c,counters2=c2,mood=u.mood,
            on_ground=u.flags1.on_ground,on_crutch=u.flags3.on_crutch,swimming=u.flags2.swimming,
            stand_max=u.status2.limbs_stand_max,stand_count=u.status2.limbs_stand_count,
            ghost=u.flags3.ghostly,scuttle=u.flags3.scuttle,gutted=u.flags2.gutted,diving=u.flags3.diving,
            speed_percent=i32(u.uwss_speed_perc),speed_add=i32(u.uwss_speed_add),
            buildup=integer(u.job.gait_buildup,0,2147483647),
            size_cur=integer(u.body.size_info.size_cur,0,2147483647),size_base=integer(u.body.size_info.size_base,0,2147483647),
            liquid_depth=u.status2.liquid_depth,liquid_type=u.status2.liquid_type.whole,
            baby=u.profession==df.profession.BABY,sneaking=u.flags1.hidden_in_ambush,
            dragging=u.relationship_ids[df.unit_relationship_type.Draggee]~=-1,
            turbospeed=df.global.debug_turbospeed,bloodsucker=flag('BLOODSUCKER'),blood_timer=0}
        if r.bloodsucker then
            local trait=dfhack.units.getMiscTrait(u,df.misc_trait_type.TimeSinceSuckedBlood,false)
            r.blood_timer=trait and trait.value or 0
        end
        local mode='WALK'
        if u.job.climb_hold.x~=-30000 or u.job.hold_itid~=-1 then mode='CLIMB'
        elseif r.swimming or u.flags3.floundering then mode='SWIM'
        elseif r.on_ground then mode='CRAWL'
        elseif flag('FLIER') and (u.status2.limbs_fly_max==0 or u.status2.limbs_fly_count>floor(u.status2.limbs_fly_max/2))
                and c.unconscious<=0 and c.webbed<10 and c2.paralysis<100 then mode='FLY' end
        r.mode=mode
        local id=df.gait_type[mode]
        r.gait_index=u.enemy.gait_index[id]
        assert(r.gait_index>=0 and r.gait_index<#u.body.body_plan.gait_info[id],'Current native gait is missing')
        local g=u.body.body_plan.gait_info[id][r.gait_index]
        r.gait={flags={layers_slow=g.flags.layers_slow,strength=g.flags.strength,agility=g.flags.agility}}
        for _,name in ipairs({'full_speed','start_speed','buildup_time','stealth_slows'}) do r.gait[name]=integer(g[name],0,2147483647) end
        r.gait_name=h.text(df.global.world.raws.creatures.action_strings[g.action_string_idx])
        local function attr(attribute_id)
            local a=u.body.physical_attrs[attribute_id]
            local raw=i32(a.value-a.soft_demotion)
            local v=raw
            if u.uwss_att_change then
                v=add(trunc(mul(v,u.uwss_att_change.phys_att_perc[attribute_id])/100),u.uwss_att_change.phys_att_add[attribute_id])
            end
            v=max(0,v)
            if (g.flags.strength or g.flags.agility) and not u.job.hunt_target and dfhack.units.isHidingCurse(u) then v=min(raw,v) end
            return v
        end
        r.strength=attr(df.physical_attribute_type.STRENGTH);r.agility=attr(df.physical_attribute_type.AGILITY)
        return r
    end)
    local function state() assert(state_ok,tostring(s));return s end
    local function skill(name)
        -- The good-vision branch is verified. Blind/extravision perception
        -- requires another native helper; never pretend it is normal sight.
        assert(u.flags2.vision_good or u.flags2.vision_damaged,'Skill adjustment for absent vision is not verified')
        s.vision=true
        return M.skill(dfhack.units.getNominalSkill(u,df.job_skill[name],true),s)
    end
    out.movement.effective_speed=read('movement.effective_speed',function()
        local v=state()
        assert(not u.flags1.rider and not u.flags1.ridden,'Mounted movement requires a verified mount calculation')
        local load=out.encumbrance.load_penalty
        assert(load.available,'Inventory load penalty is unavailable')
        v.crutch_skill=skill('CRUTCH_WALK')
        v.swimming_skill=h.caste.flags.CAN_SWIM and skill('SWIMMING') or 0
        -- The special default swimming skill is at most 1 and so cannot
        -- change the speed multiplier, which starts at skill 2.
        local cost,components=M.movement(v,load.movement_cost_added,true)
        local unloaded=M.movement(v,0,true)
        local full=M.movement(v,load.movement_cost_added,false)
        local result=M.speed(cost)
        result.available=true;result.source=M.build;result.units='native_speed'
        result.meaning='Calculated current gait rate in the same units as the HUD; not wall-clock tiles/second or a guarantee that movement is possible'
        result.gait=v.gait_name;result.gait_type=v.mode;result.gait_index=v.gait_index
        result.gait_buildup=v.buildup;result.components=components
        result.unloaded=M.speed(unloaded);result.at_full_gait=M.speed(full)
        load.speed_reduction_percent=100*(1-result.value/result.unloaded.value)
        load.movement_delay_increase_percent=100*(result.movement_delay/result.unloaded.movement_delay-1)
        load.comparison='Same current gait and character state with the inventory load contribution removed; native clamp retained'
        return result
    end)
    out.semantics.physical_needs='Native warning stages from the verified build; raw timers and exemptions retained. Labels do not choose dispatch or interruption policy'
    out.semantics.movement='Build-scoped calculation independent of UI/HUD visibility. Unknown inputs, unsupported mounted/vision states, and 32-bit arithmetic overflow are explicit'
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
