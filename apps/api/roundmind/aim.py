"""Event-only metrics. No hit accuracy, reaction time or decision score is inferred."""
from bisect import bisect_right
from collections import defaultdict
from math import hypot, isfinite
import re
from uuid import NAMESPACE_URL, uuid5

PARSER_VERSION = 'demoparser2-0.42.1'
RULE_VERSION = 'aim-events-v1'
MOVEMENT_THRESHOLD = 34.0
GUNS = frozenset('ak47 m4a1 m4a1_silencer aug sg556 galilar famas awp ssg08 scar20 g3sg1 mac10 mp9 mp7 mp5sd ump45 p90 bizon nova xm1014 mag7 sawedoff m249 negev glock hkp2000 usp_silencer p250 fiveseven tec9 cz75a elite deagle revolver'.split())


class AnalysisError(RuntimeError):
    pass


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        n = float(value)
        return n if isfinite(n) else None
    except (TypeError, ValueError):
        return None


def identity(value):
    # A float Steam ID may have lost precision in a DataFrame. Do not guess it.
    if isinstance(value, float) or value is None:
        return None
    text = str(value)
    return text if re.fullmatch(r'[0-9]{1,20}', text) and int(text) > 0 else None


def text(value, limit=80):
    return re.sub(r'[\x00-\x1f\x7f]', '', str('' if value is None else value))[:limit]


def flag(value):
    if value is True:
        return True
    if value is False:
        return False
    n = number(value)
    return bool(n) if n in {0,1} else None


def weapon_name(value):
    return text(value).lower().removeprefix('weapon_')


def build_report(demo_id, sha256, header, raw, participation):
    quality = defaultdict(int)
    starts = sorted((r for r in raw.get('round_freeze_end', []) if number(r.get('tick')) is not None), key=lambda r:int(r['tick']))
    ends = sorted((r for r in raw.get('round_end', []) if number(r.get('tick')) is not None), key=lambda r:int(r['tick']))
    rounds = []
    for i, start in enumerate(starts):
        if flag(start.get('is_warmup_period')) is not False:
            quality['excluded_round_context'] += 1
            continue
        from_tick = int(start['tick'])
        next_start = int(starts[i+1]['tick']) if i+1 < len(starts) else float('inf')
        end = next((r for r in ends if from_tick <= int(r['tick']) < next_start), None)
        if end is None:
            quality['incomplete_rounds'] += 1
            continue
        no = len(rounds)+1
        rounds.append({'id':str(uuid5(NAMESPACE_URL,f'{demo_id}:round:{no}')), 'round_no':no,
                       'start_tick':from_tick, 'end_tick':int(end['tick']), 'winner':None})
    if not rounds:
        raise AnalysisError('no_confirmed_rounds')
    ticks = [r['start_tick'] for r in rounds]

    def round_at(tick):
        index = bisect_right(ticks, tick)-1
        if index >= 0 and tick <= rounds[index]['end_tick']:
            return rounds[index]
        return None

    players = {}
    participant_rounds = defaultdict(set)
    def player(pid, name=None):
        if pid not in players:
            players[pid] = {'player_id':pid, 'name':text(name) or pid, 'shots':0, 'damage':0, 'kills':0,
                'headshot_kills':0, 'known_headshot_kills':0,'unknown_headshot_kills':0,
                'speed_sample_count':0,'moving_shots':0, 'findings':[], 'weapons':{}, 'events':[],
                'coverage_complete':True}
        elif name:
            players[pid]['name'] = text(name) or players[pid]['name']
        return players[pid]

    for row in participation:
        pid = identity(row.get('steamid'))
        tick = number(row.get('tick'))
        team = number(row.get('team_num'))
        if pid and tick is not None and team in {2,3}:
            r = round_at(int(tick))
            if r and int(tick) == r['start_tick']:
                participant_rounds[pid].add(r['id'])
                player(pid, row.get('name'))
    events = []
    candidates = {}
    for kind in ['weapon_fire','player_hurt','player_death']:
        for index, row in enumerate(raw.get(kind, [])):
            tick = number(row.get('tick'))
            if tick is None:
                quality['missing_tick'] += 1
                continue
            r = round_at(int(tick))
            if not r or flag(row.get('is_warmup_period')) is True:
                quality['outside_confirmed_rounds'] += 1
                continue
            weapon = weapon_name(row.get('weapon'))
            if weapon not in GUNS:
                quality['non_gun_events'] += 1
                continue
            prefix = 'user' if kind == 'weapon_fire' else 'attacker'
            pid = identity(row.get(prefix+'_steamid'))
            target = identity(row.get('user_steamid')) if kind != 'weapon_fire' else None
            if not pid:
                quality['missing_identity'] += 1
                continue
            p = player(pid, row.get(prefix+'_name'))
            team = number(row.get(prefix+'_team_num'))
            target_team = number(row.get('user_team_num')) if target else None
            if team not in {2,3} or (kind != 'weapon_fire' and target_team not in {2,3}):
                quality['unknown_team_events'] += 1
                p['coverage_complete'] = False
                if kind != 'weapon_fire':
                    continue
            if kind != 'weapon_fire' and (not target or target == pid or team == target_team):
                quality['friendly_or_self_events'] += 1
                continue
            entry = {'id':str(uuid5(NAMESPACE_URL,f'{demo_id}:{kind}:{index}')), 'round_id':r['id'],
                     'round_no':r['round_no'], 'tick':int(tick), 'type':kind, 'actor':pid,
                     'target':target, 'actor_name':p['name'], 'target_name':text(row.get('user_name')) if target else None,
                     'weapon':weapon, 'speed':None, 'damage':None, 'headshot':None,
                     'position':None,'view_angles':None,'is_airborne':None,'ducked':None,'hitgroup':None}
            bucket = p['weapons'].setdefault(weapon, {'weapon':weapon,'shots':0,'damage':0,'kills':0})
            if kind == 'weapon_fire':
                coords=[number(row.get('user_'+axis)) for axis in ['X','Y','Z']]
                if all(value is not None for value in coords): entry['position']=coords
                angles=[number(row.get('user_pitch')),number(row.get('user_yaw'))]
                if all(value is not None for value in angles): entry['view_angles']=angles
                entry['is_airborne']=flag(row.get('user_is_airborne'))
                entry['ducked']=flag(row.get('user_ducked'))
                p['shots'] += 1
                bucket['shots'] += 1
                vx,vy = number(row.get('user_velocity_X')),number(row.get('user_velocity_Y'))
                if vx is not None and vy is not None:
                    speed = hypot(vx,vy)
                    entry['speed'] = round(speed,3)
                    p['speed_sample_count'] += 1
                    if speed > MOVEMENT_THRESHOLD:
                        p['moving_shots'] += 1
                        key = (pid,r['id'])
                        if key not in candidates or candidates[key]['speed'] < entry['speed']:
                            candidates[key] = entry
            elif kind == 'player_hurt':
                damage = number(row.get('dmg_health'))
                if damage is None or damage < 0:
                    quality['missing_damage'] += 1
                    p['coverage_complete'] = False
                    continue
                entry['damage'] = int(damage)
                hitgroup=number(row.get('hitgroup'))
                entry['hitgroup']=int(hitgroup) if hitgroup is not None else None
                p['damage'] += int(damage)
                bucket['damage'] += int(damage)
            else:
                p['kills'] += 1
                bucket['kills'] += 1
                entry['headshot'] = flag(row.get('headshot'))
                if entry['headshot'] is None:
                    p['unknown_headshot_kills'] += 1
                else:
                    p['known_headshot_kills'] += 1
                    p['headshot_kills'] += int(entry['headshot'])
            events.append(entry)
            p['events'].append(entry['id'])
    for index,row in enumerate(raw.get('bullet_impact', [])):
        tick=number(row.get('tick'))
        pid=identity(row.get('user_steamid'))
        r=round_at(int(tick)) if tick is not None else None
        coords=[number(row.get(axis)) for axis in ['x','y','z']]
        if not r or not pid or any(value is None for value in coords):
            continue
        events.append({'id':str(uuid5(NAMESPACE_URL,f'{demo_id}:bullet_impact:{index}')),
                       'round_id':r['id'],'round_no':r['round_no'],'tick':int(tick),'type':'bullet_impact',
                       'actor':pid,'target':None,'actor_name':text(row.get('user_name')) or pid,
                       'target_name':None,'weapon':weapon_name(row.get('user_active_weapon_name')),
                       'speed':None,'damage':None,'headshot':None,'position':coords,
                       'view_angles':None,'is_airborne':None,'ducked':None})
    for (pid,_), event in candidates.items():
        players[pid]['findings'].append({
            'finding_id':'movement:'+event['id'], 'scope':'personal','category':'movement_at_fire','severity':'info',
            'summary':f"记录回合 {event['round_no']} 存在移动开火样本", 'player_id':pid,
            'observed_facts':[f"Tick {event['tick']}，{event['weapon']} 开火时水平速度 {event['speed']} u/s"],
            'inferences':['超过34 u/s观察阈值；是否影响该武器精度尚未判定'],
            'counterfactual_options':['结合该回合意图核查是否需要停稳再开火；不应只凭速度认定失误'],
            'evidence_refs':[{'round_id':event['round_id'],'round_no':event['round_no'],
                              'start_tick':event['tick'],'end_tick':event['tick'],'event_id':event['id']}],
            'confidence':None,'uncertainty_reasons':['观察阈值未经武器/版本校准，不是失误概率'],
            'model_version':'none','rule_version':RULE_VERSION,'review_status':'unreviewed'})
    for p in players.values():
        if quality.get('missing_identity', 0):
            p['coverage_complete'] = False
        p['headshot_kill_ratio'] = p['headshot_kills']/p['known_headshot_kills'] if p['known_headshot_kills'] else None
        p['damage_per_shot'] = p['damage']/p['shots'] if p['shots'] and p['coverage_complete'] else None
        p['moving_shot_ratio'] = p['moving_shots']/p['speed_sample_count'] if p['speed_sample_count'] else None
        p['speed_coverage'] = p['speed_sample_count']/p['shots'] if p['shots'] else None
        p['participated_rounds'] = len(participant_rounds[p['player_id']]) if p['player_id'] in participant_rounds else None
        p['weapons'] = list(p['weapons'].values())
        p['findings'] = p['findings'][:100]
    return {'match_id':demo_id,'sha256':sha256,'map':text(header.get('map_name')) or 'unknown',
            'data_origin':'user_demo','parser_version':PARSER_VERSION,'rule_version':RULE_VERSION,
            'movement_threshold':MOVEMENT_THRESHOLD,'round_numbering':'confirmed_recorded_rounds',
            'rounds':rounds,'players':sorted(players.values(),key=lambda p:p['shots'],reverse=True),
            'events':sorted(events,key=lambda e:(e['tick'],e['id'])), 'quality':dict(quality),
            'limitations':['不是命中率或真实反应时间分析','伤害使用原始dmg_health记录，可能含过量伤害',
                           '移动开火是观察样本，不自动判定失误','记录回合号不保证等于官方比赛回合号']}
