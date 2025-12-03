from flask import Flask, request, jsonify
import geopandas as gpd
import os
from functools import lru_cache

app = Flask(__name__)

print("Loading shapefiles...")
PARCELS = gpd.read_file('data/Parcels_export.shp')
STREETS = gpd.read_file('data/Streets.shp')
print(f"Loaded {len(PARCELS)} parcels and {len(STREETS)} streets")

def normalize_parcel_id(zillow_id):
    zillow_id = str(zillow_id).strip().upper()
    if zillow_id.startswith('R'):
        zillow_id = zillow_id[1:]
    try:
        return str(int(zillow_id))
    except ValueError:
        return zillow_id

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'parcels': len(PARCELS), 'streets': len(STREETS)})

@app.route('/calculate-frontage', methods=['POST'])
def calculate_frontage():
    data = request.get_json()
    parcel_id = data.get('parcel_id')
    
    if not parcel_id:
        return jsonify({'success': False, 'error': 'parcel_id required'}), 400
    
    normalized_id = normalize_parcel_id(parcel_id)
    
    PARCELS['PROP_ID_NORMALIZED'] = PARCELS['PROP_ID'].astype(str).str.strip()
    parcel = PARCELS[PARCELS['PROP_ID_NORMALIZED'] == normalized_id]
    
    if parcel.empty:
        return jsonify({
            'success': False,
            'error': 'Parcel not found',
            'original_id': parcel_id,
            'normalized_id': normalized_id
        })
    
    parcel_row = parcel.iloc[0]
    parcel_geom = parcel_row.geometry
    
    public_streets = STREETS[STREETS['CFCC'].isin(['A41', 'A51'])]
    intersecting = public_streets[public_streets.intersects(parcel_geom.boundary)]
    
    roads = []
    total_frontage = 0
    
    for idx, street in intersecting.iterrows():
        intersection = parcel_geom.boundary.intersection(street.geometry)
        length_ft = intersection.length if not intersection.is_empty else 0
        
        if length_ft > 0:
            street_parts = [
                str(street.get('FEDIRP', '')),
                str(street.get('FENAME', '')),
                str(street.get('FETYPE', '')),
                str(street.get('FEDIRS', ''))
            ]
            street_name = ' '.join([p for p in street_parts if p and p != 'None']).strip()
            
            roads.append({
                'street_name': street_name or 'Unnamed Road',
                'frontage_ft': round(length_ft, 2),
                'road_type': street.get('CFCC', 'Unknown')
            })
            total_frontage += length_ft
    
    roads.sort(key=lambda x: x['frontage_ft'], reverse=True)
    
    return jsonify({
        'success': True,
        'total_frontage_ft': round(total_frontage, 2),
        'road_count': len(roads),
        'roads': roads,
        'original_id': parcel_id,
        'normalized_id': normalized_id,
        'parcel_address': f"{parcel_row.get('situs_num', '')} {parcel_row.get('situs_stre', '')}".strip()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
