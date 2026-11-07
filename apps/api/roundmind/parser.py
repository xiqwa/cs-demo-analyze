from pathlib import Path
from .aim import build_report, AnalysisError


def records(frame):
    if hasattr(frame, 'to_dict'):
        return frame.to_dict(orient='records')
    return []


def parse_demo(path: Path, demo_id: str, sha256: str):
    from demoparser2 import DemoParser
    try:
        parser = DemoParser(str(path))
        header = parser.parse_header()
        names = ['round_freeze_end','round_end','weapon_fire','player_hurt','player_death','bullet_impact']
        try:
            parsed = parser.parse_events(names, player=['team_num','velocity_X','velocity_Y','X','Y','Z','pitch','yaw','is_airborne','ducked','active_weapon_name'], other=['is_warmup_period'])
        except Exception:
            try:
                parsed = parser.parse_events(names, player=['team_num','velocity_X','velocity_Y'], other=['is_warmup_period'])
            except Exception:
                parsed = parser.parse_events(names, player=['team_num'], other=['is_warmup_period'])
        raw = {name:records(frame) for name,frame in parsed}
        starts = [int(row['tick']) for row in raw.get('round_freeze_end',[]) if row.get('tick') is not None]
        try:
            participants = records(parser.parse_ticks(['team_num'], ticks=starts)) if starts else []
        except Exception:
            participants = []  # Participation is unknown, never inferred from shots.
        report = build_report(demo_id,sha256,header,raw,participants)
        report['participation_available'] = bool(participants)
        if not participants:
            report['quality']['missing_participation_snapshot'] = 1
        return report
    except AnalysisError:
        raise
    except BaseException:
        # Parser failures (including Rust panic wrappers) must not become reports.
        raise AnalysisError('unsupported_or_corrupt_demo') from None
