"""Auditable GB network prototype. All builds work offline from local snapshots."""
from pathlib import Path
from collections import defaultdict, Counter
import argparse, csv, hashlib, html, json, math, re
import pandas as pd
import networkx as nx
import folium
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
FOREIGN = {'VIKING LINK':'DK', 'NSL SUB':'NO', 'NEMO SUB':'BE', 'MOYLW SUB':'GB-NIR',
           'IFA2 SUB':'FR', 'IFA SUB':'FR', 'EWC SUB':'IE', 'ELECLINK SUB':'FR', 'BRITNED SUB':'NL'}

def value(v):
    if v is None: return None
    if isinstance(v, (list, dict)): return v
    try:
        if pd.isna(v): return None
    except (TypeError, ValueError): pass
    if hasattr(v, 'item'): v = v.item()
    if isinstance(v, float) and not math.isfinite(v): return None
    return v

def number(v):
    try: return value(float(str(v).replace(',', '')))
    except (TypeError, ValueError): return None

def clean(s): return str(s).strip() if value(s) is not None else ''
def key(s): return re.sub(r'[^A-Z0-9]', '', clean(s).upper())
def token(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()[:16]


def tooltip_text(text):
    # Folium renders tooltip HTML inside a JavaScript template literal.
    return html.escape(text).replace('`', '&#96;').replace('$', '&#36;').replace('\\', '&#92;')

def technology_groups(text):
    text=clean(text).lower(); result=set()
    for group,words in {
        'wind':['wind'], 'solar':['solar','pv array'], 'nuclear':['nuclear'],
        'pumped':['pump'], 'hydro':['hydro'], 'gas':['natural gas','ccgt','gas turbine','gas reciprocating'],
        'oil':['diesel','gas oil','oil'], 'waste':['efw','incineration','waste'],
        'biomass':['biomass'], 'storage':['energy storage','battery'], 'coal':['coal']}.items():
        if any(w in text for w in words): result.add(group)
    if 'pumped' in result: result.discard('hydro')
    if 'thermal' in text: result.update(['gas','oil','coal'])
    if 'ocgt' in text: result.update(['gas','oil'])
    return result

def write_csv(path, rows, columns=None):
    columns = columns or list(dict.fromkeys(k for r in rows for k in r)) or ['id']
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore'); writer.writeheader()
        for row in rows: writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict,list)) else value(v) for k,v in row.items()})

def write_json(path, data): path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), 'utf-8')

def load_csv(path):
    for enc in ['utf-8-sig','cp1252']:
        try: return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError: pass
    raise ValueError('Unsupported encoding: '+str(path))

def source_attrs(sid, manifest, row=None, sheet=None):
    m = manifest.get(sid, {})
    return dict(source_id=sid, source_url=m.get('source_page'), source_date=m.get('source_date'),
                source_sha256=m.get('sha256'), source_row=row, source_sheet=sheet)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--cardiff',type=Path,help='Local Cardiff Data.xlsx')
    parser.add_argument('--dukes',type=Path,help='Local DUKES 5.11 workbook')
    parser.add_argument('--repd',type=Path,help='Local official REPD CSV')
    parser.add_argument('--tec',type=Path,help='Local NESO TEC CSV')
    parser.add_argument('--interconnector-register',type=Path,help='Local NESO interconnector CSV')
    args=parser.parse_args(); root=args.root.resolve(); raw=root/'data/raw'; out=root/'data/normalized'; exports=root/'exports'
    out.mkdir(parents=True, exist_ok=True); exports.mkdir(parents=True, exist_ok=True)
    manifest=json.loads((raw/'manifest.json').read_text('utf-8')) if (raw/'manifest.json').exists() else {}
    paths={'cardiff':args.cardiff or raw/'cardiff.xlsx','dukes':args.dukes or raw/'dukes.xlsx',
           'repd':args.repd or raw/'repd.csv','transmission-entry-capacity-tec-register':args.tec or raw/'neso_tec.csv',
           'interconnector-register':args.interconnector_register or raw/'neso_interconnectors.csv'}
    explicit_inputs = {args.cardiff, args.dukes, args.repd, args.tec, args.interconnector_register} - {None}
    for sid,path in paths.items():
        if path.exists():
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            expected = manifest.get(sid, {}).get('sha256')
            if path.resolve().parent == raw.resolve() and expected not in (None, digest):
                raise ValueError('Snapshot integrity failure: '+sid)
            if digest != expected:
                publisher = manifest.get(sid, {}).get('source_page')
                manifest[sid] = dict(source_page=publisher, sha256=digest,
                    local_file=path.name, note='Local input; edition and licence not verified')
        else:
            if path in explicit_inputs:
                parser.error(f'File not found: {path}')
            manifest.setdefault(sid, {})['used_in_build'] = False
    if not paths['cardiff'].exists(): raise FileNotFoundError('Place Cardiff Data.xlsx in data/raw/cardiff.xlsx or pass --cardiff PATH')
    graph=nx.MultiGraph(name='GB transmission model and verified interconnector corridors', schema_version='1.0')
    issues=[]; terminals={}; by_coordinate=defaultdict(list)
    def issue(kind, **data): issues.append(dict(kind=kind,**data))
    workbook=pd.ExcelFile(paths['cardiff'])
    required={'Terminal','Line','Transformer','Static Generator','Synchnonise Generator'}
    if not required.issubset(workbook.sheet_names): raise ValueError('Unexpected Cardiff workbook schema')
    sheets={s:pd.read_excel(workbook,s,skiprows=[1]) for s in workbook.sheet_names}
    # Keep one terminal per voltage bus. Never collapse a whole substation to one node.
    for i,r in sheets['Terminal'].iterrows():
        name=clean(r['Name']); lat=number(r['Latitude / Northing']); lon=number(r['Longitude / Easting'])
        if name in terminals: raise ValueError('Duplicate Cardiff terminal: '+name)
        if lat is not None and lon is not None and not (-90<=lat<=90 and -180<=lon<=180): raise ValueError('Invalid coordinate')
        nid='bus:'+token(name); attrs=dict(id=nid,name=name,node_type='substation_bus',country=FOREIGN.get(name,'GB'),
            voltage_kv=number(r['Voltage']),latitude=lat,longitude=lon,status='model_snapshot',
            coordinate_quality='published_model_point',**source_attrs('cardiff',manifest,int(i)+3,'Terminal'))
        terminals[name]=attrs
        if name not in FOREIGN: graph.add_node(nid,**attrs)
        if lat is not None and lon is not None: by_coordinate[(lat,lon)].append(attrs)
    # All foreign equivalent lines in this workbook have zero electrical parameters.
    # Retain their rows in the audit, replace only selected links with operator facts.
    for i,r in sheets['Line'].iterrows():
        a,b=clean(r['Terminal i']),clean(r['Terminal j']); eid=f'cardiff:line:{i+3}'
        for name in [a,b]:
            if name and name not in terminals:
                # A line's explicit endpoint is a valid topology reference even
                # when the Terminal sheet omits it. Keep it without coordinates.
                nid='bus:'+token(name)
                attrs=dict(id=nid,name=name,node_type='unlocated_bus_reference',country=None,
                    voltage_kv=None,latitude=None,longitude=None,status='model_snapshot',
                    coordinate_quality='missing_terminal_record',**source_attrs('cardiff',manifest,int(i)+3,'Line'))
                terminals[name]=attrs; graph.add_node(nid,**attrs)
                issue('line_endpoint_missing_terminal_metadata',name=name,id=nid)
        if not a or not b:
            issue('line_missing_terminal',id=eid,from_name=a,to_name=b); continue
        if a in FOREIGN or b in FOREIGN:
            issue('foreign_equivalent_line_excluded',id=eid,name=clean(r['Name']),from_name=a,to_name=b); continue
        attrs=dict(id=eid,name=clean(r['Name']),edge_type='ac_line',status='model_snapshot',
            evidence='explicit_terminal_columns',length_km=number(r['Length']),voltage_kv=number(r['Rtd.Volt.']),
            nominal_current_ka=number(r['Inom']),r_ohm=number(r['R1']),x_ohm=number(r['X1']),
            **source_attrs('cardiff',manifest,int(i)+3,'Line'))
        if attrs['length_km']==0:
            attrs['length_km']=None; issue('zero_model_length',id=eid)
        attrs['zero_impedance'] = attrs['r_ohm'] == 0 and attrs['x_ohm'] == 0
        if attrs['zero_impedance']:
            issue('zero_line_impedance', id=eid)
        stated_voltage = attrs['voltage_kv']
        bus_voltages = [terminals[end]['voltage_kv'] for end in (a, b)]
        attrs['terminal_voltage_mismatch'] = stated_voltage is not None and any(
            voltage is not None and voltage != stated_voltage for voltage in bus_voltages
        )
        if attrs['terminal_voltage_mismatch']:
            issue('line_terminal_voltage_mismatch', id=eid, line_kv=stated_voltage,
                  from_name=a, to_name=b, terminal_kv=bus_voltages)
        graph.add_edge(terminals[a]['id'],terminals[b]['id'],key=eid,**attrs)
    # No terminal columns are supplied for transformers. Resolve only when a named
    # terminal anchors the site and each winding voltage has exactly one bus there.
    for i,r in sheets['Transformer'].iterrows():
        name=clean(r['Name']); eid=f'cardiff:transformer:{i+3}'; winding=re.fullmatch(r'(\d+)-(\d+)kV',clean(r['HV/LV']))
        anchor=terminals.get(name)
        if not anchor or not winding:
            issue('transformer_unresolved',id=eid,name=name,reason='No exact terminal anchor or invalid winding'); continue
        site=by_coordinate.get((anchor['latitude'],anchor['longitude']),[])
        sides=[[n for n in site if n['voltage_kv']==float(v) and n['name'] not in FOREIGN] for v in winding.groups()]
        if any(len(side)!=1 for side in sides):
            issue('transformer_unresolved',id=eid,name=name,reason='Ambiguous/missing winding buses',candidates=[[n['name'] for n in s] for s in sides]); continue
        graph.add_edge(sides[0][0]['id'],sides[1][0]['id'],key=eid,id=eid,name=name,edge_type='transformer',
            status='model_snapshot',evidence='source_transformer_name_and_unique_colocated_winding_buses',
            rated_mva=number(r['Snom']),winding_kv=clean(r['HV/LV']),r_pu=number(r['r (Sbase)']),x_pu=number(r['x (Sbase)']),
            **source_attrs('cardiff',manifest,int(i)+3,'Transformer'))
    # Generator names often match buses, but the workbook has no explicit generator
    # terminal field. Preserve inventory/candidates; do not manufacture attachments.
    generators=[]
    for sheet in ['Static Generator','Synchnonise Generator']:
        for i,r in sheets[sheet].iterrows():
            name=clean(r['Name']); candidate=terminals.get(name)
            generators.append(dict(id='model_generator:'+token(sheet+':'+str(i)),name=name,
                record_type='model_generator_record',technology=clean(r['Plant Category']),subcategory=clean(r['Subcategory']),
                active_power_mw=number(r['Act.Pow.']),max_power_mw=number(r.get('Pmax',r.get('Max.Active Power Limit'))),
                candidate_terminal_id=candidate['id'] if candidate else None,attachment_status='not_asserted_name_only',
                **source_attrs('cardiff',manifest,int(i)+3,sheet)))
    for s,df in sheets.items():
        write_csv(out/('cardiff_'+re.sub('[^a-z]+','_',s.lower())+'.csv'),[{**{str(k):value(v) for k,v in r.items()},'source_excel_row':int(i)+3} for i,r in df.iterrows()])

    # Inventory is separate from the network: unmatched plants do not become fake
    # disconnected electrical nodes. REPD and DUKES overlap and are not summed.
    plants=[]; transform=Transformer.from_crs(27700,4326,always_xy=True)
    def coordinates(country,x,y):
        if clean(country) not in {'England','Scotland','Wales'}: return None,None
        x,y=number(x),number(y)
        if x is None or y is None: return None,None
        lon,lat=transform.transform(x,y)
        if not (-10<=lon<=3 and 49<=lat<=62): return None,None
        return lat,lon
    if paths['dukes'].exists():
        tab=pd.read_excel(paths['dukes'],sheet_name='5.11 Full list',header=None)
        header=next(i for i,row in tab.iterrows() if 'Site Name' in row.tolist() and 'DESNZ site code' in row.tolist())
        df=pd.read_excel(paths['dukes'],sheet_name='5.11 Full list',header=header)
        for i,r in df.iterrows():
            if not clean(r['Site Name']) or number(r['InstalledCapacity (MW)']) is None: continue
            lat,lon=coordinates(r['Country'],r['X-Coordinate'],r['Y-Coordinate'])
            plants.append(dict(id='dukes:'+token(str(i)+clean(r['DESNZ site code'])),name=clean(r['Site Name']),
                registry_id=clean(r['DESNZ site code']),country='GB' if clean(r['Country'])!='Northern Ireland' else 'GB-NIR',
                region=clean(r['Region']),technology=clean(r['Technology']),fuel=clean(r['Primary Fuel']),
                capacity_mw=number(r['InstalledCapacity (MW)']),latitude=lat,longitude=lon,status='operational_at_source_date',
                source_crs='EPSG:27700 for England/Scotland/Wales; NI not transformed',
                **source_attrs('dukes',manifest,int(i)+header+2,'5.11 Full list')))
    if paths['repd'].exists():
        df=load_csv(paths['repd'])
        for i,r in df.iterrows():
            lat,lon=coordinates(r['Country'],r['X-coordinate'],r['Y-coordinate'])
            plants.append(dict(id='repd:'+clean(r['Ref ID']),name=clean(r['Site Name']),registry_id=clean(r['Ref ID']),
                country='GB-NIR' if clean(r['Country'])=='Northern Ireland' else 'GB',region=clean(r['Region']),
                technology=clean(r['Technology Type']),capacity_mw=number(r['Installed Capacity (MWelec)']),
                latitude=lat,longitude=lon,status=clean(r['Development Status (short)']),
                original_x=number(r['X-coordinate']),original_y=number(r['Y-coordinate']),
                source_crs='EPSG:27700 assumed for GB X/Y; NI not transformed',
                **source_attrs('repd',manifest,int(i)+2)))
    plant_index=defaultdict(list)
    for p in plants:
        if p['country']=='GB' and p['status'] in {'Operational','operational_at_source_date'}: plant_index[key(p['name'])].append(p)
    # Allow only exact normalised station names, unique source preference DUKES,
    # and exact site label + stated voltage. No nearest-neighbour connections.
    def resolve_site(label):
        volts=re.search(r'(\d+)\s*kV',label,re.I)
        if not volts: return None
        site=re.sub(r'\b(substation|gsp|gis)\b','',label,flags=re.I)
        site=re.sub(r'\d+\s*kV','',site,flags=re.I)
        matches=[n for n in terminals.values() if n['name'] not in FOREIGN and key(n['name'])==key(site) and n['voltage_kv']==float(volts.group(1))]
        return matches[0] if len(matches)==1 else None
    connection_audit=[]
    if paths['transmission-entry-capacity-tec-register'].exists():
        tec=load_csv(paths['transmission-entry-capacity-tec-register'])
        for i,r in tec.iterrows():
            if (number(r['MW Connected']) or 0)<=0: continue
            candidates=plant_index.get(key(r['Project Name']),[])
            preferred=[p for p in candidates if p['source_id']=='dukes'] or candidates
            site=resolve_site(clean(r['Connection Site']))
            audit=dict(project_name=clean(r['Project Name']),connection_site=clean(r['Connection Site']),
                project_number=clean(r['Project Number']),source_row=int(i)+2,plant_candidates=[p['id'] for p in preferred],
                resolved_terminal_id=site['id'] if site else None, neso_status=clean(r['Project Status']))
            if audit['neso_status'].casefold() != 'built':
                audit['resolution']='rejected_register_status'; connection_audit.append(audit); continue
            if len(preferred)!=1 or site is None:
                audit['resolution']='unresolved_exact_match'; connection_audit.append(audit); continue
            p=preferred[0]
            plant_tech=technology_groups(p['technology']+' '+clean(p.get('fuel')))
            tec_tech=technology_groups(r['Plant Type'])
            capacity=p['capacity_mw']; connected=number(r['MW Connected'])
            if not plant_tech.intersection(tec_tech) or not capacity or not .5<=connected/capacity<=2:
                audit['resolution']='rejected_technology_or_capacity_conflict'
                audit['registry_technology']=p['technology']; audit['neso_technology']=clean(r['Plant Type'])
                audit['registry_capacity_mw']=capacity; audit['connected_tec_mw']=connected
                connection_audit.append(audit); continue
            if p['latitude'] is not None and site['latitude'] is not None:
                # A conservative rejection guard, never a method to create edges.
                distance=math.hypot((p['latitude']-site['latitude'])*111,(p['longitude']-site['longitude'])*65)
                if distance>50:
                    audit['resolution']='rejected_coordinate_conflict'; connection_audit.append(audit); continue
            nid='plant:'+p['id']; graph.add_node(nid,**{**p,'id':nid,'node_type':'power_plant'})
            eid='neso:connection:'+str(i+2)
            graph.add_edge(nid,site['id'],key=eid,id=eid,name=clean(r['Project Name']),edge_type='plant_connection',
                status='connected_at_register_date',evidence='NESO_site_exact_registry_name_compatible_technology_capacity_guard_and_bus_voltage',
                connected_tec_mw=number(r['MW Connected']),project_number=clean(r['Project Number']),
                **source_attrs('transmission-entry-capacity-tec-register',manifest,int(i)+2))
            audit['resolution']='connected'; connection_audit.append(audit)

    refs=load_csv(root/'data/reference/interconnectors.csv'); ic_register=[]
    if paths['interconnector-register'].exists(): ic_register=load_csv(paths['interconnector-register']).to_dict('records')
    aliases={'britned':'Britned','nemo':'Nemo Link','ewic':'East West Interconnector','greenlink':'Greenlink','ifa':'IFA Interconnector',
             'ifa2':'IFA2 Interconnector','eleclink':'ElecLink','neuconnect':'NeuConnect Interconnector'}
    selected_ic=[]
    for _,r in refs.iterrows():
        rid=clean(r['id']); status=clean(r['status']); ends=[]
        for side in ['gb','foreign']:
            bus=terminals.get(clean(r[side+'_cardiff_terminal']))
            # Share the Les Mandarins endpoint at grid level, not converter level.
            if rid=='eleclink' and side=='foreign': bus=terminals.get('IFA SUB')
            if bus:
                nid=bus['id']
                if nid not in graph: graph.add_node(nid,**bus)
            else:
                country='GB' if side=='gb' else clean(r['country']); site=clean(r[side+'_site'])
                nid='endpoint:'+country+':'+token(site)
                graph.add_node(nid,id=nid,name=site,node_type='interconnector_grid_endpoint',country=country,
                    latitude=None,longitude=None,voltage_kv=None,status=status,
                    coordinate_quality='not_available',source_url=clean(r['source_url']),source_date=clean(r['source_date']))
                issue('endpoint_not_geolocated',interconnector=rid,side=side,name=site)
            ends.append(nid)
        registered=[rr for rr in ic_register if key(rr['Project Name'])==key(aliases[rid])]
        registered=registered[0] if len(registered)==1 else {}
        if not registered: issue('interconnector_register_unmatched',interconnector=rid)
        row={str(k):value(v) for k,v in r.items()}
        row.update(neso_connection_site=value(registered.get('Connection Site')),neso_status=value(registered.get('Project Status')),
            neso_import_current_mw=number(registered.get('MW Import - Current')),neso_export_current_mw=number(registered.get('MW Export - Current')),
            neso_contracted_effective_date=value(registered.get('MW Effective From')),
            register_source_sha256=manifest.get('interconnector-register',{}).get('sha256'))
        if rid=='neuconnect': issue('neuconnect_source_disagreement',operator_site='Grain West',register_site=row['neso_connection_site'],note='No alias asserted; operator planned commissioning 2028; register contractual date is not commissioning')
        eid='interconnector:'+rid
        graph.add_edge(*ends,key=eid,id=eid,name=clean(r['name']),edge_type='hvdc_interconnector',status=status,
            nominal_capacity_mw=number(r['nominal_capacity_mw']),representation='aggregate_grid_to_grid_corridor',
            evidence='operator_or_regulator_endpoints_plus_NESO' if registered else 'operator_or_regulator_endpoints',
            length_km=None,voltage_kv=None,
            source_url=clean(r['source_url']),source_date=clean(r['source_date']),notes=clean(r['notes']),
            neso_connection_site=row['neso_connection_site'],neso_import_current_mw=row['neso_import_current_mw'],
            neso_export_current_mw=row['neso_export_current_mw'],register_source_sha256=row['register_source_sha256'])
        selected_ic.append(row)

    nodes=[{k:value(v) for k,v in attrs.items()} for _,attrs in graph.nodes(data=True)]
    edges=[dict(source=u,target=v,**{k:value(x) for k,x in attrs.items()}) for u,v,attrs in graph.edges(data=True)]
    write_csv(out/'nodes.csv',nodes); write_csv(out/'edges.csv',edges)
    write_csv(out/'plant_inventory.csv',plants); write_csv(out/'model_generators.csv',generators)
    write_csv(out/'plant_connections_audit.csv',connection_audit); write_csv(out/'interconnectors.csv',selected_ic)
    write_json(out/'issues.json',issues); write_json(out/'build_sources.json',manifest)
    active=graph.copy()
    active.remove_edges_from([(u,v,k) for u,v,k,d in active.edges(keys=True,data=True) if d['status']=='under_construction'])
    active.remove_nodes_from([n for n in active if graph.nodes[n].get('status')=='under_construction' and active.degree(n)==0])
    for name,g in [('grid',graph),('grid_active',active)]:
        write_json(exports/(name+'.json'),nx.node_link_data(g,edges='edges'))
        sanitized=nx.MultiGraph(**g.graph)
        for nid,attrs in g.nodes(data=True): sanitized.add_node(nid,**{k:v for k,v in attrs.items() if v is not None})
        for u,v,k,attrs in g.edges(keys=True,data=True): sanitized.add_edge(u,v,key=k,**{a:b for a,b in attrs.items() if b is not None})
        nx.write_graphml(sanitized,exports/(name+'.graphml'))
    report=dict(scope='GB transmission model + FR/NL/BE/IE endpoints; DE construction scenario; NI/NO/DK excluded',
        nodes=graph.number_of_nodes(),edges=graph.number_of_edges(),active_nodes=active.number_of_nodes(),active_edges=active.number_of_edges(),
        node_types=dict(Counter(d['node_type'] for _,d in graph.nodes(data=True))),
        edge_types=dict(Counter(d['edge_type'] for *_,d in graph.edges(data=True))),
        active_components=nx.number_connected_components(active),active_largest_component=len(max(nx.connected_components(active),key=len)),
        plant_inventory_records=len(plants),plant_inventory_not_deduplicated=True,model_generator_records=len(generators),
        issues=dict(Counter(i['kind'] for i in issues)),
        connected_plant_match_method='Exact normalised name + technology overlap + TEC/capacity 0.5..2 + no coordinate conflict over 50 km; no fuzzy/proximity attachments',
        map_nodes_without_coordinates=sum(n.get('latitude') is None or n.get('longitude') is None for n in nodes),
        limitations=['Mixed source dates; model_snapshot does not assert current operational state',
            'Transformer endpoints resolved only from exact named bus and unique colocated winding voltages; ambiguous rows excluded',
            'Cardiff generator names are not explicit attachment columns; candidates only, no invented generator edges',
            'Unknown endpoint coordinates omitted from map, retained in graph and endpoint schematic',
            'Corridor straight lines are connectivity illustrations, not cable routes',
            'Plant inventory overlaps between DUKES/REPD; do not sum; exact name matches require review',
            'NI inventory retained separately; no NI network; no power-flow, economic development or reliability claims'])
    # Leaflet map: no coordinates invented; line rendering explicitly schematic.
    m=folium.Map(location=[54,-2],zoom_start=5,tiles='OpenStreetMap',prefer_canvas=True)
    layers={k:folium.FeatureGroup(name=label,show=show).add_to(m) for k,label,show in [
        ('ac_line','Линии GB: модель Cardiff',True),('transformer','Трансформаторы: места подключения',False),
        ('plant_connection','Реестровые сопоставления станций NESO',True),
        ('hvdc_interconnector','Действующие интерконнекторы с координатами',True)]}
    colours={'ac_line':'#54748b','transformer':'#8b5cf6','plant_connection':'#16a34a','hvdc_interconnector':'#e56a13'}
    map_edges = defaultdict(Counter)
    transformers_at = Counter()
    for u,v,d in graph.edges(data=True):
        a,b=graph.nodes[u],graph.nodes[v]
        layer = d['edge_type']
        if d['status'] == 'under_construction':
            map_edges[layer]['construction_in_schematic'] += 1
            continue
        if any(n.get('latitude') is None or n.get('longitude') is None for n in [a,b]):
            map_edges[layer]['missing_coordinates'] += 1
            continue
        points = [(n['latitude'], n['longitude']) for n in (a, b)]
        if points[0] == points[1]:
            map_edges[layer]['coincident_endpoints'] += 1
            if layer == 'transformer':
                transformers_at[points[0]] += 1
            continue
        map_edges[layer]['polylines'] += 1
        folium.PolyLine(points,color=colours[layer],
            weight=3 if d['edge_type']=='hvdc_interconnector' else 1,opacity=.7,
            tooltip=tooltip_text(d['name']+' | '+d['edge_type']+' | '+d['status'])).add_to(layers[layer])
    for location, count in transformers_at.items():
        folium.CircleMarker(location, radius=4, color=colours['transformer'],
                            tooltip=f'Трансформаторы в модели: {count}').add_to(layers['transformer'])
    report['map_edges'] = {name: dict(counts) for name, counts in map_edges.items()}
    report['map_transformer_marker_sites'] = len(transformers_at)
    write_json(exports/'summary.json',report)
    buses=folium.FeatureGroup(name='Узлы модели и терминалы',show=False).add_to(m)
    for _,n in graph.nodes(data=True):
        if n.get('latitude') is None or n.get('longitude') is None: continue
        folium.CircleMarker([n['latitude'],n['longitude']],radius=3,color='#16a34a' if n['node_type']=='power_plant' else '#1d4ed8',
            tooltip=tooltip_text(n['name']+' | '+n['node_type']),fill=True).add_to(buses)
    folium.LayerControl(collapsed=False).add_to(m)
    attribution = ('<a href="https://doi.org/10.17035/cardiff.28152161.v1">Morteza Shafiekhani, Cardiff University, 2025</a> '
                   '(<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>, адаптация).<br>'
                   '<a href="https://www.neso.energy/data-portal/neso-open-licence">Supported by National Energy SO Open Data</a>.<br>'
                   'Contains public sector information licensed under the Open Government Licence v3.0.')
    m.get_root().html.add_child(folium.Element(
        '<div style="position:fixed;bottom:25px;left:20px;z-index:9999;background:white;padding:12px;'
        'max-width:420px;border:1px solid #aaa;font:13px sans-serif"><b>Электросеть GB</b><br>'
        'Прямые отрезки обозначают связи. Точки без координат указаны в '
        '<a href="endpoint_schematic.html">схеме интерконнекторов</a>.<br>' + attribution + '</div>'))
    map_html = m.get_root().render()
    (exports/'map.html').write_text(re.sub(r'[ \t]+(?=\r?$)', '', map_html, flags=re.M), 'utf-8')
    # Offline endpoint schematic includes every corridor, even missing coordinates.
    blocks=[]
    for r in selected_ic:
        blocks.append('<tr><td>'+html.escape(r['name'])+'</td><td>'+html.escape(r['gb_site'])+'</td><td>↔</td><td>'+html.escape(r['foreign_site'])+'</td><td>'+html.escape(r['country'])+'</td><td>'+str(r['nominal_capacity_mw'])+'</td><td>'+html.escape(r['status'])+'</td><td><a href="'+html.escape(r['source_url'],quote=True)+'">Источник</a></td></tr>')
    (exports/'endpoint_schematic.html').write_text('<!doctype html><html lang="ru"><meta charset="utf-8"><title>Связи GB</title><style>body{font:16px system-ui;margin:40px;color:#172536}table{border-collapse:collapse}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:left}</style><h1>Межсетевые связи GB</h1><p>Схема точек подключения. NeuConnect строится и учитывается отдельно.</p><table><tr><th>Связь</th><th>GB</th><th></th><th>Внешний узел</th><th>Страна</th><th>Номинал, МВт</th><th>Статус</th><th></th></tr>'+''.join(blocks)+'</table><p>'+attribution+'<br><a href="../data/raw/manifest.json">Источники и SHA-256</a> · <a href="map.html">Карта</a></p></html>','utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
