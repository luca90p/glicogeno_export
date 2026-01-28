import math
import xml.etree.ElementTree as ET

from data_models import SportType


def parse_zwo_file(uploaded_file, ftp_watts, thr_hr, sport_type):
    try:
        xml_content = uploaded_file.getvalue().decode('utf-8')
        root = ET.fromstring(xml_content)
        intensity_series = []
        total_duration_sec = 0
        total_weighted_if = 0
        for steady_state in root.findall('.//SteadyState'):
            try:
                dur = int(steady_state.get('Duration'))
                pwr = float(steady_state.get('Power'))
                for _ in range(math.ceil(dur / 60)):
                    intensity_series.append(pwr)
                total_duration_sec += dur
                total_weighted_if += pwr * (dur / 60)
            except:
                continue
        total_min = math.ceil(total_duration_sec / 60)
        avg_val = 0
        if total_min > 0:
            avg_if = total_weighted_if / total_min
            if sport_type == SportType.CYCLING:
                avg_val = avg_if * ftp_watts
            elif sport_type == SportType.RUNNING:
                avg_val = avg_if * thr_hr
            else:
                avg_val = avg_if * 180
            return intensity_series, total_min, avg_val, avg_val
        return [], 0, 0, 0
    except:
        return [], 0, 0, 0
