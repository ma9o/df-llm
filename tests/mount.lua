local source=...
local names={}
local function test(name,fn)local ok,e=pcall(fn);assert(ok,name..': '..tostring(e));names[#names+1]=name end
local function fixture()
    local f={realized={},deleted=0}
    local me={id=1,pos={x=5,y=5,z=0},flags1={rider=false},relationship_ids={[0]=-1,[6]=-1,[8]=-1},actions={}}
    local horse={id=7,pos={x=6,y=5,z=0},race=1,caste=0,flags1={ridden=false},relationship_ids={[0]=-1,[6]=-1,[8]=-1},inventory={}}
    local dog={id=8,pos={x=6,y=6,z=0},race=2,caste=0,flags1={ridden=false},relationship_ids={[0]=-1,[6]=-1,[8]=-1},inventory={}}
    local units={[7]=horse,[8]=dog}
    local raws={[1]={caste={[0]={flags={MOUNT=true}}}},[2]={caste={[0]={flags={MOUNT=false}}}}}
    local function coord()return {assign=function(self,p)self.x=p.x;self.y=p.y;self.z=p.z end}end
    local function class(name)
        return {new=function()
            local c={source=coord(),dest=coord(),hasRealize=function()return not f.refuse end,
                doRealize=function(self)f.realized[#f.realized+1]={class=name,animal=self.animal,rider=self.riderposition}
                    if name=='adventure_movement_mountst' then me.actions[1]={type=3} end end,
                delete=function()f.deleted=f.deleted+1 end}
            return c
        end}
    end
    horse.hist_figure_id=12884;dog.hist_figure_id=-1
    local env=setmetatable({df={global={world={units={active={horse,dog}}}},
        adventure_movement_mountst=class('adventure_movement_mountst'),
        adventure_movement_dismountst=class('adventure_movement_dismountst'),
        adventure_movement_claim_petst=class('adventure_movement_claim_petst'),
        adventure_movement_lead_animalst=class('adventure_movement_lead_animalst'),
        adventure_movement_stop_lead_animalst=class('adventure_movement_stop_lead_animalst'),
        unit_relationship_type={PetOwner=0,Draggee=6,RiderMount=8},
        rider_positions_type={STANDARD=0},unit_action_type={[3]='Mount'},
        creature_raw={find=function(id)return raws[id]end},
        unit={find=function(id)return units[id]end}},
        dfhack={world={getAdventurer=function()return me end},
            units={isVisible=function(u)return not u.hidden end,isHidden=function(u)return u.hidden or false end,
                isDead=function(u)return u.dead or false end,isTame=function()return true end,
                isPet=function(u)return u.relationship_ids[0]==1 end,getReadableName=function(u)return 'unit '..u.id end}}},
        {__index=_ENV})
    f.api=assert(load(source,'mount-fixture','t',env))({text=function(s)return s end,array=function()return {}end})
    f.me,f.horse,f.dog=me,horse,dog
    return f
end
test('state reads rider flags relationships queued actions and the animal without writing',function()
    local f=fixture();local s=f.api.state(7)
    assert(s.available and s.rider==false and s.mount_id==-1 and s.animal.id==7 and s.animal.adjacent and s.animal.mount_capable)
    assert(#s.queued==0 and s.animal.owner_id==-1 and not s.animal.pet)
    assert(f.api.state(99).animal.present==false and f.api.state().animal==nil)
end)
test('mount realizes the native option for an adjacent visible mount only',function()
    local f=fixture();local r=f.api.submit({command='mount',unit_id=7})
    assert(r.command=='mount' and r.animal_id==7 and #f.realized==1 and f.realized[1].animal==f.horse)
    assert(f.realized[1].rider==0 and f.deleted==1 and f.api.state(7).queued[1]=='Mount')
    f=fixture();f.horse.pos.x=9;assert(not pcall(f.api.submit,{command='mount',unit_id=7}) and #f.realized==0)
    f=fixture();f.horse.hidden=true;assert(not pcall(f.api.submit,{command='mount',unit_id=7}))
    f=fixture();assert(not pcall(f.api.submit,{command='mount',unit_id=8})) -- a dog is not a mount
    f=fixture();f.me.flags1.rider=true;assert(not pcall(f.api.submit,{command='mount',unit_id=7}))
    f=fixture();f.refuse=true;assert(not pcall(f.api.submit,{command='mount',unit_id=7}) and f.deleted==1)
end)
test('dismount needs a rider and claim or lead need the adjacent animal',function()
    local f=fixture();assert(not pcall(f.api.submit,{command='dismount'}))
    f.me.flags1.rider=true;assert(f.api.submit({command='dismount'}).command=='dismount' and f.realized[1].animal==nil)
    f=fixture();assert(f.api.submit({command='claim_pet',unit_id=8}).animal_id==8) -- any adjacent animal
    assert(f.api.submit({command='lead_animal',unit_id=7}).command=='lead_animal')
    assert(not pcall(f.api.submit,{command='gallop',unit_id=7}))
end)
test('companions lists owned pets and the mount with stable figure ids',function()
    local f=fixture();f.horse.relationship_ids[0]=1;f.me.relationship_ids[8]=8;f.me.flags1.rider=true
    local c=f.api.companions()
    assert(c.available and #c.companions==2 and c.rider and c.mount_id==8)
    local by={};for _,a in ipairs(c.companions)do by[a.id]=a end
    assert(by[7].figure_id==12884 and by[7].pet and not by[7].mount and by[7].cargo_count==0)
    assert(by[8].mount and by[8].figure_id==nil)
end)
return {passed=#names,tests=names,game_inputs=0}
