from flask import Flask, request, jsonify
import geopandas as gpd
import os

app = Flask(__name__)

print("Loading shapefiles...")
PARCELS = gpd.read_file('data/Parcels_export.shp', engine='pyogrio')
STREETS = gpd.read_file('data/Streets.shp', engine='pyogrio')
print(f"Loaded {len(PARCELS)} parcels and {len(STREETS)} streets")

def normalize_parcel_id(parcel_id):
    """Remove R prefix and leading zeros"""
    parcel_id = str(parcel_id).upper().strip()
    if parcel_id.startswith('R'):
        parcel_id = parcel_id[1:]
    return str(int(parcel_id))

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "parcels_loaded": len(PARCELS),
        "streets_loaded": len(STREETS)
    })

@app.route('/sample-parcels', methods=['GET'])
def sample_parcels():
    """Return sample parcel IDs with frontage for testing"""
    samples = []
    public_streets = STREETS[STREETS['CFCC'].isin(['A41', 'A51'])]
    
    # Check first 100 parcels to find some with frontage
    for idx, parcel in PARCELS.head(100).iterrows():
        parcel_boundary = parcel.geometry.boundary
        has_frontage = False
        
        for _, street in public_streets.iterrows():
            intersection = parcel_boundary.intersection(street.geometry)
            if not intersection.is_empty and intersection.length > 0:
                has_frontage = True
                break
        
        if has_frontage:
            samples.append({
                "parcel_id": str(parcel['PROP_ID']),
                "address": f"{parcel.get('situs_num', '')} {parcel.get('situs_stre', '')}, {parcel.get('situs_city', '')}".strip()
            })
            
            if len(samples) >= 10:
                break
    
    return jsonify({
        "sample_count": len(samples),
        "samples": samples
    })

@app.route('/calculate-frontage', methods=['POST'])
def calculate_frontage():
    data = request.get_json()
    parcel_id = data.get('parcel_id')
    include_private = data.get('include_private', False)
    
    if not parcel_id:
        return jsonify({"error": "parcel_id required"}), 400
    
    normalized_id = normalize_parcel_id(parcel_id)
    parcel_match = PARCELS[PARCELS['PROP_ID'].astype(str) == normalized_id]
    
    if parcel_match.empty:
        return jsonify({
            "error": "Parcel not found",
            "parcel_id": parcel_id,
            "normalized_id": normalized_id
        }), 404
    
    parcel = parcel_match.iloc[0]
    parcel_geom = parcel.geometry
    parcel_boundary = parcel_geom.boundary
    
    if include_private:
        filtered_streets = STREETS
    else:
        filtered_streets = STREETS[STREETS['CFCC'].isin(['A41', 'A51'])]
    
    frontages = []
    total_frontage = 0
    
    for idx, street in filtered_streets.iterrows():
        intersection = parcel_boundary.intersection(street.geometry)
        if not intersection.is_empty:
            frontage_ft = intersection.length
            if frontage_ft > 0:
                street_name = f"{street.get('FEDIRP', '')} {street.get('FENAME', '')} {street.get('FETYPE', '')} {street.get('FEDIRS', '')}".strip()
                
                cfcc = street.get('CFCC', '')
                if cfcc == 'A41':
                    road_type = 'Secondary Highway'
                elif cfcc == 'A51':
                    road_type = 'Local Road'
                elif cfcc == 'PR':
                    road_type = 'Private Road'
                else:
                    road_type = f'Other ({cfcc})'
                
                frontages.append({
                    "street_name": street_name,
                    "frontage_ft": round(frontage_ft, 2),
                    "road_type": road_type,
                    "cfcc": cfcc
                })
                total_frontage += frontage_ft
    
    frontages.sort(key=lambda x: x['frontage_ft'], reverse=True)
    address = f"{parcel.get('situs_num', '')} {parcel.get('situs_stre', '')}, {parcel.get('situs_city', '')} {parcel.get('situs_zip', '')}".strip()
    
    return jsonify({
        "parcel_id": parcel_id,
        "normalized_id": normalized_id,
        "address": address,
        "total_frontage_ft": round(total_frontage, 2),
        "road_count": len(frontages),
        "roads": frontages,
        "include_private": include_private
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
