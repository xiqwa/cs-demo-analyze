"""Synthetic event fixtures: never exposed as real Demo analysis."""
import pytest
from roundmind.aim import build_report, AnalysisError


def fixture_events():
    context = {'is_warmup_period':False}
    def e(tick, **kw): return {'tick':tick, **context, **kw}
    return {
        'round_freeze_end':[e(100)], 'round_end':[e(300,winner=2)],
        'weapon_fire':[
            e(120,user_steamid='111',user_name='Test A',user_team_num=2,weapon='ak47',user_velocity_X=40,user_velocity_Y=0),
            e(140,user_steamid='111',user_name='Test A',user_team_num=2,weapon='ak47',user_velocity_X=None,user_velocity_Y=None),
            e(160,user_steamid='111',user_name='Test A',user_team_num=2,weapon='ak47',user_velocity_X=0,user_velocity_Y=0),
            e(170,user_steamid='111',user_name='Test A',user_team_num=2,weapon='hegrenade'),
            e(400,user_steamid='111',user_team_num=2,weapon='ak47')],
        'player_hurt':[
            e(120,attacker_steamid='111',user_steamid='222',attacker_team_num=2,user_team_num=3,weapon='ak47',dmg_health=80),
            e(121,attacker_steamid='111',user_steamid='222',attacker_team_num=2,user_team_num=3,weapon='ak47',dmg_health=80),
            e(150,attacker_steamid='111',user_steamid='333',attacker_team_num=2,user_team_num=2,weapon='ak47',dmg_health=50)],
        'player_death':[e(121,attacker_steamid='111',user_steamid='222',attacker_team_num=2,user_team_num=3,weapon='ak47',headshot=True)]}


def test_metrics_exclude_non_guns_friendly_and_outside_rounds():
    report = build_report('demo-id', 'a'*64, {'map_name':'de_mirage'}, fixture_events(), [])
    player = next(p for p in report['players'] if p['player_id']=='111')
    assert player['shots'] == 3
    assert player['damage'] == 160
    assert player['kills'] == 1
    assert player['headshot_kill_ratio'] == 1
    assert player['moving_shot_ratio'] == 0.5
    assert player['speed_sample_count'] == 2
    assert player['damage_per_shot'] == pytest.approx(160/3)
    finding = player['findings'][0]
    assert finding['evidence_refs'][0]['start_tick'] == 120
    assert finding['confidence'] is None
    assert report['data_origin'] == 'user_demo'
    assert len(report['rounds']) == 1


def test_missing_speed_never_becomes_stationary():
    events = fixture_events()
    for shot in events['weapon_fire']:
        shot.pop('user_velocity_X',None)
        shot.pop('user_velocity_Y',None)
    report=build_report('demo-id','a'*64,{},events,[])
    p=next(p for p in report['players'] if p['player_id']=='111')
    assert p['moving_shot_ratio'] is None
    assert p['speed_sample_count'] == 0
    assert p['findings'] == []


def test_warmup_and_incomplete_rounds_not_mixed():
    events=fixture_events()
    events['round_freeze_end'].insert(0,{'tick':10,'is_warmup_period':True})
    events['round_freeze_end'].append({'tick':500,'is_warmup_period':False})
    report=build_report('demo-id','a'*64,{},events,[])
    assert len(report['rounds']) == 1
    assert report['quality']['incomplete_rounds'] == 1


def test_unknown_context_rejected():
    events=fixture_events()
    events['round_freeze_end'][0].pop('is_warmup_period')
    with pytest.raises(AnalysisError,match='no_confirmed_rounds'):
        build_report('demo-id','a'*64,{},events,[])


def test_unknown_headshot_is_not_zero_and_unknown_team_is_excluded():
    events=fixture_events()
    events['player_death'][0]['headshot']=None
    events['player_hurt'][0]['attacker_team_num']=None
    report=build_report('demo-id','a'*64,{},events,[])
    p=next(p for p in report['players'] if p['player_id']=='111')
    assert p['headshot_kill_ratio'] is None
    assert p['unknown_headshot_kills'] == 1
    assert report['quality']['unknown_team_events'] >= 1
    assert p['damage_per_shot'] is None


def test_each_fire_keeps_optional_observations_and_unknown_team_fire():
    raw=fixture_events()
    raw['weapon_fire'][0].update(user_team_num=None,user_X=100,user_Y=-200,user_Z=10,user_pitch=-2,user_yaw=90,user_ducked=True,user_is_airborne=False)
    report=build_report('demo-id','a'*64,{},raw,[])
    shots=[e for e in report['events'] if e['type']=='weapon_fire']
    assert len(shots)==3
    shot=next(e for e in shots if e['tick']==120)
    assert shot['position']==[100,-200,10]
    assert shot['view_angles']==[-2,90]
    assert shot['ducked'] is True and shot['is_airborne'] is False
    assert report['quality']['unknown_team_events']==1
