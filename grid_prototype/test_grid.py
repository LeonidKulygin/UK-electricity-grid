"""Data-integrity and domain regression checks against built local exports."""
from pathlib import Path
import hashlib, json, unittest
import networkx as nx
import pandas as pd
from build_grid import technology_groups

ROOT=Path(__file__).resolve().parent

class GridChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full=nx.node_link_graph(json.loads((ROOT/'exports/grid.json').read_text('utf-8')),edges='edges')
        cls.active=nx.read_graphml(ROOT/'exports/grid_active.graphml',force_multigraph=True)

    def test_snapshot_checksums(self):
        manifest=json.loads((ROOT/'data/raw/manifest.json').read_text('utf-8'))
        for source in manifest.values():
            if source.get('file') and source.get('sha256'):
                path = ROOT/'data/raw'/source['file']
                if source['file'] == 'repd.csv' and not path.exists():
                    continue
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),source['sha256'])

    def test_active_scope_and_construction(self):
        edges=[d for *_,d in self.active.edges(data=True) if d['edge_type']=='hvdc_interconnector']
        self.assertEqual(len(edges),7)
        self.assertFalse(any(d.get('status')=='under_construction' for *_,d in self.active.edges(data=True)))
        self.assertEqual({d.get('country') for _,d in self.active.nodes(data=True)}-{'GB',None}, {'NL','BE','IE','FR'})
        self.assertIn('interconnector:neuconnect',{d['id'] for *_,d in self.full.edges(data=True)})
        self.assertNotIn('interconnector:neuconnect',{d['id'] for *_,d in self.active.edges(data=True)})

    def test_no_synthetic_cluster_or_foreign_plant_edges(self):
        self.assertTrue(self.full.is_multigraph())
        allowed={'ac_line','transformer','plant_connection','hvdc_interconnector'}
        for u,v,d in self.full.edges(data=True):
            self.assertIn(d['edge_type'],allowed)
            self.assertTrue(d.get('source_url'))
            self.assertTrue(d.get('evidence'))
            if d['edge_type']=='plant_connection':
                self.assertEqual(self.full.nodes[u].get('country'),'GB')
                self.assertEqual(self.full.nodes[v].get('country'),'GB')
        ids=[d['id'] for *_,d in self.full.edges(data=True)]
        self.assertEqual(len(ids),len(set(ids)))

    def test_graphml_json_round_trip(self):
        other=nx.read_graphml(ROOT/'exports/grid.graphml',force_multigraph=True)
        self.assertEqual(set(other),set(self.full))
        self.assertEqual(other.number_of_edges(),self.full.number_of_edges())
        self.assertEqual({d['id'] for *_,d in other.edges(data=True)},{d['id'] for *_,d in self.full.edges(data=True)})

    def test_physical_input_flags_and_map_accounting(self):
        summary = json.loads((ROOT/'exports/summary.json').read_text('utf-8'))
        lines = [data for *_, data in self.full.edges(data=True) if data['edge_type'] == 'ac_line']
        self.assertEqual(len(lines), 788)
        self.assertEqual(sum(data['zero_impedance'] for data in lines), 51)
        self.assertEqual(sum(data['terminal_voltage_mismatch'] for data in lines), 11)
        self.assertEqual(nx.number_of_selfloops(self.full), 0)
        for edge_type, counts in summary['map_edges'].items():
            self.assertEqual(sum(counts.values()), summary['edge_types'][edge_type])
        self.assertEqual(summary['map_edges']['hvdc_interconnector']['polylines'], 5)

    def test_false_positive_station_names_are_rejected(self):
        audit=pd.read_csv(ROOT/'data/normalized/plant_connections_audit.csv')
        for name in ['Coventry','Immingham','Spalding','Sutton Bridge']:
            matching=audit[audit.project_name.eq(name)]
            self.assertFalse(matching.empty,name)
            self.assertTrue(matching.resolution.str.startswith(('rejected', 'unresolved')).all(),name)
        self.assertFalse(technology_groups('Solar').intersection(technology_groups('CCGT')))

    def test_unknown_coordinates_not_fabricated(self):
        missing=[d for _,d in self.full.nodes(data=True) if d.get('coordinate_quality') in {'missing_terminal_record','not_available'}]
        self.assertTrue(missing)
        self.assertTrue(all(d.get('latitude') is None and d.get('longitude') is None for d in missing))
        for filename in ['map.html','endpoint_schematic.html']:
            text=(ROOT/'exports'/filename).read_text('utf-8')
            self.assertIn('<html',text.lower())
            self.assertGreater(len(text),1000)

if __name__=='__main__': unittest.main()
