--@ module=true
--luacheck: globals factory
local function build(...)
-- Native aimed-combat decisions. Only the active mode owns these pointers.
-- No target, weapon, body part, attack style or confirmation is chosen here.
local h=...
local M={}
local function integer(value,name)
    assert(type(value)=='number' and value==math.floor(value),name..' is unavailable')
    return value
end
local function flags(value)
    local out=h.array()
    for k,v in pairs(value) do if type(k)=='string' and v==true then out[#out+1]=k end end
    table.sort(out);return out
end
local function part_name(unit,id)
    if id<0 then return nil end
    local parts=unit.body.body_plan.body_parts
    assert(id<#parts,'Body part is outside the active target anatomy')
    return h.text(parts[id].name_singular[0])
end
local function attack_description(item,index)
    if item then
        local name=h.text(dfhack.items.getReadableDescription(item))
        if item:getType()==df.item_type.WEAPON then
            local def=dfhack.items.getSubtypeDef(item:getType(),item:getSubtype())
            assert(def and index>=0 and index<#def.attacks,'Weapon attack definition is unavailable')
            return h.text(def.attacks[index].verb_2nd)..' with '..name
        end
        -- Shields, tools and improvised weapons can have native default attacks
        -- that are not itemdef weapon attacks. Keep their identity, not a guess.
        return name..' (native attack '..index..')'
    end
    local player=assert(dfhack.world.getAdventurer(),'No local adventurer')
    local attacks=player.body.body_plan.attacks
    assert(index>=0 and index<#attacks,'Natural attack definition is unavailable')
    local attack=attacks[index]
    local part=integer(attack.conflict_check_bp,'Natural attack required body part')
    local name=part_name(player,part)
    return h.text(attack.verb_2nd)..' ('..(name or h.text(attack.name))..')',part
end
function M.menu(out)
    local panel=df.global.game.main_interface.adventure.attack
    assert(panel.open and df.adventure_interface_attack_mode_type[panel.mode]==out.mode
        and (out.mode=='AIM_TARGET' or out.mode=='AIM_ATTACK'),'Aiming mode is not active')
    local ok,err=pcall(function()
        local list,field,drag,count=h.bindings.combat_list(out)
        out.scroll=integer(panel[field],'Combat scroll');out.scrolling=drag
        out.total=count
        if count>500 then out.truncated=true end
        local target=assert(panel.attack_unit,'Native attack target is unavailable')
        assert(target.id==out.target_unit_id,'Native attack target changed')
        if out.mode=='AIM_ATTACK' then
            out.attack_flags=flags(panel.aim_attack_flag)
            out.charge_restriction=df.charge_restrict_type[panel.aim_attack_charge_restrict]
            assert(out.charge_restriction,'Native charge restriction is unavailable')
            out.style_keys={}
            if h.bindings.combat_supported(out) then
                for _,name in ipairs({'quick','heavy','wild','precise','charge','multi'}) do
                    local key=name:upper()..'_ATTACK'
                    if type(df.interface_key[key])=='number' then out.style_keys[name]=key end
                end
            end
        end
        for i=0,math.min(count,500)-1 do
            local entry=list[i]
            assert(entry,'Native aim choice is unavailable')
            local bp=integer(entry.target_bp,'Target body part')
            local option={index=i,body_part_id=bp,label=part_name(target,bp)}
            if out.mode=='AIM_TARGET' then
                option.id='combat-aim-target:'..target.id..':'..i..':'..bp
                option.kind='body_part'
                option.hit_chance_adjustment=integer(entry.initial_hit_chance_adjustment,'Hit adjustment')
                option.hit_squareness_adjustment=integer(entry.initial_hit_squareness_adjustment,'Squareness adjustment')
                option.flags=flags(entry.modifier_flags)
            else
                local item=entry.attack_item
                option.item_id=item and item.id or -1
                option.attack_index=integer(entry.attack_index,'Attack index')
                option.id=table.concat({'combat-aim-attack',target.id,i,bp,option.item_id,option.attack_index},':')
                option.kind='attack'
                option.label,option.required_body_part_id=attack_description(item,option.attack_index)
                option.hit_chance_adjustment=integer(entry.hit_chance_adjustment,'Hit adjustment')
                option.hit_squareness_adjustment=integer(entry.hit_squareness_adjustment,'Squareness adjustment')
                option.flags=flags(entry.flags)
            end
            h.bindings.bind(option,i,out.scroll,h.bindings.combat_supported(out))
            out.options[#out.options+1]=option
        end
        if not h.bindings.combat_supported(out) then
            out.selection_unavailable='No verified native aiming keys for this build'
        end
    end)
    if not ok then
        out.selection_unavailable=tostring(err):sub(1,240)
        for _,option in ipairs(out.options) do option.selection=nil end
    end
    return out
end
return M

end
if dfhack_flags and dfhack_flags.module then factory=build else return build(...) end
