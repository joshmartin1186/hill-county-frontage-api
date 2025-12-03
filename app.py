from flask import Flask, request, jsonify
import geopandas as gpd
import os

app = Flask(__name__)

print("Loading shapefiles...")
# Explicitly use pyogrio engine
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

@app.route('/calculate-frontage', methods=['POST'])
def calculate_frontage():
    data = request.get_json()
    parcel_id = data.get('parcel_id')
    
    if not parcel_id:
        return jsonify({"error": "parcel_id required"}), 400
    
    # Normalize the parcel ID
    normalized_id = normalize_parcel_id(parcel_id)
    
    # Find the parcel
    parcel_match = PARCELS[PARCELS['PROP_ID'].astype(str) == normalized_id]
    
    if parcel_match.empty:
        return jsonify({
            "error": "Parcel not found",
            "parcel_id": parcel_id,
            "normalized_id": normalized_id
        }), 404
    
    parcel = parcel_match.iloc[0]
    parcel_geom = parcel.geometry
    
    # Get parcel boundary
    parcel_boundary = parcel_geom.boundary
    
    # Find intersecting streets (only public roads: A41, A51)
    public_streets = STREETS[STREETS['CFCC'].isin(['A41', 'A51'])]
    
    # Calculate frontage for each street
    frontages = []
    total_frontage = 0
    
    for idx, street in public_streets.iterrows():
        intersection = parcel_boundary.intersection(street.geometry)
        if not intersection.is_empty:
            frontage_ft = intersection.length
            if frontage_ft > 0:
                street_name = f"{street.get('FEDIRP', '')} {street.get('FENAME', '')} {street.get('FETYPE', '')} {street.get('FEDIRS', '')}".strip()
                road_type = 'Secondary Highway' if street['CFCC'] == 'A41' else 'Local Road'
                
                frontages.append({
                    "street_name": street_name,
                    "frontage_ft": round(frontage_ft, 2),
                    "road_type": road_type
                })
                total_frontage += frontage_ft
    
    # Sort by frontage descending
    frontages.sort(key=lambda x: x['frontage_ft'], reverse=True)
    
    # Build address
    address = f"{parcel.get('situs_num', '')} {parcel.get('situs_stre', '')}, {parcel.get('situs_city', '')} {parcel.get('situs_zip', '')}".strip()
    
    return jsonify({
        "parcel_id": parcel_id,
        "normalized_id": normalized_id,
        "address": address,
        "total_frontage_ft": round(total_frontage, 2),
        "road_count": len(frontages),
        "roads": frontages
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
