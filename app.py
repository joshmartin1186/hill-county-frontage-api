from flask import Flask, request, jsonify
import geopandas as gpd
import os

app = Flask(__name__)

print("Loading shapefiles...")
PARCELS = gpd.read_file('data/Parcels_export.shp', engine='pyogrio')
STREETS = gpd.read_file('data/Streets.shp', engine='pyogrio')
print(f"Loaded {len(PARCELS)} parcels and {len(STREETS)} streets")

if PARCELS.crs != STREETS.crs:
    STREETS = STREETS.to_crs(PARCELS.crs)

def normalize_parcel_id(parcel_id):
    parcel_id = str(parcel_id).upper().strip()
    if parcel_id.startswith('R'):
        parcel_id = parcel_id[1:]
    return str(int(parcel_id))

def calculate_frontage_with_tolerance(parcel_geom, tolerance, include_private):
    """Calculate frontage with specific parameters"""
    parcel_boundary = parcel_geom.boundary.buffer(tolerance)
    
    if include_private:
        filtered_streets = STREETS
    else:
        filtered_streets = STREETS[
            STREETS['CFCC'].notna() & 
            STREETS['CFCC'].isin(['A41', 'A51'])
        ]
    
    frontages = []
    for idx, street in filtered_streets.iterrows():
        intersection = parcel_boundary.intersection(street.geometry)
        if not intersection.is_empty and intersection.length > 0:
            street_name = f"{street.get('FEDIRP', '')} {street.get('FENAME', '')} {street.get('FETYPE', '')} {street.get('FEDIRS', '')}".strip()
            cfcc = street.get('CFCC', 'Unknown')
            
            if cfcc == 'A41':
                road_type = 'Secondary Highway'
            elif cfcc == 'A51':
                road_type = 'Local Road'
            elif cfcc == 'PR' or 'PR' in str(street.get('FENAME', '')):
                road_type = 'Private Road'
            else:
                road_type = f'Other ({cfcc})'
            
            frontages.append({
                "street_name": street_name,
                "frontage_ft": round(intersection.length, 2),
                "road_type": road_type,
                "cfcc": str(cfcc) if cfcc else "None"
            })
    
    frontages.sort(key=lambda x: x['frontage_ft'], reverse=True)
    return frontages

def get_nearby_streets(parcel_geom, buffer_distance=1000):
    """Find streets near the parcel"""
    buffered = parcel_geom.buffer(buffer_distance)
    nearby_streets = STREETS[STREETS.intersects(buffered)]
    
    street_info = []
    for idx, street in nearby_streets.iterrows():
        street_name = f"{street.get('FEDIRP', '')} {street.get('FENAME', '')} {street.get('FETYPE', '')} {street.get('FEDIRS', '')}".strip()
        distance = parcel_geom.distance(street.geometry)
        cfcc = street.get('CFCC')
        
        if cfcc == 'A41':
            road_type = 'Secondary Highway'
        elif cfcc == 'A51':
            road_type = 'Local Road'
        elif cfcc == 'PR':
            road_type = 'Private Road'
        else:
            road_type = 'Other/Unknown'
        
        street_info.append({
            "street_name": street_name,
            "cfcc": str(cfcc) if cfcc is not None else "NULL",
            "road_type": road_type,
            "distance_ft": round(distance, 2)
        })
    
    street_info.sort(key=lambda x: x['distance_ft'])
    return street_info

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "parcels_loaded": len(PARCELS),
        "streets_loaded": len(STREETS)
    })

@app.route('/analyze-parcel', methods=['POST'])
def analyze_parcel():
    """
    Comprehensive analysis endpoint for LLM consumption.
    Returns multiple calculations at different tolerances plus nearby roads.
    """
    data = request.get_json()
    parcel_id = data.get('parcel_id')
    
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
    
    # Get address
    address = f"{parcel.get('situs_num', '')} {parcel.get('situs_stre', '')}, {parcel.get('situs_city', '')} {parcel.get('situs_zip', '')}".strip()
    
    # Multiple calculations at different tolerances
    strict = calculate_frontage_with_tolerance(parcel_geom, 30, False)
    moderate = calculate_frontage_with_tolerance(parcel_geom, 100, False)
    permissive_public = calculate_frontage_with_tolerance(parcel_geom, 500, False)
    permissive_all = calculate_frontage_with_tolerance(parcel_geom, 500, True)
    
    # Nearby streets inventory
    nearby = get_nearby_streets(parcel_geom, 1000)
    
    # Calculate totals
    strict_total = sum(r['frontage_ft'] for r in strict)
    moderate_total = sum(r['frontage_ft'] for r in moderate)
    permissive_public_total = sum(r['frontage_ft'] for r in permissive_public)
    permissive_all_total = sum(r['frontage_ft'] for r in permissive_all)
    
    return jsonify({
        "parcel_id": parcel_id,
        "normalized_id": normalized_id,
        "address": address,
        "parcel_area_sqft": round(parcel_geom.area, 2),
        "parcel_bounds": list(parcel_geom.bounds),
        
        # Analysis 1: Strict (high confidence)
        "strict_analysis": {
            "description": "30ft tolerance, public roads only (A41, A51)",
            "confidence": "high",
            "total_frontage_ft": round(strict_total, 2),
            "road_count": len(strict),
            "roads": strict
        },
        
        # Analysis 2: Moderate (medium confidence)
        "moderate_analysis": {
            "description": "100ft tolerance, public roads only",
            "confidence": "medium",
            "total_frontage_ft": round(moderate_total, 2),
            "road_count": len(moderate),
            "roads": moderate
        },
        
        # Analysis 3: Permissive public (lower confidence)
        "permissive_public_analysis": {
            "description": "500ft tolerance, public roads only",
            "confidence": "low",
            "total_frontage_ft": round(permissive_public_total, 2),
            "road_count": len(permissive_public),
            "roads": permissive_public
        },
        
        # Analysis 4: All roads (context only)
        "permissive_all_analysis": {
            "description": "500ft tolerance, includes private roads",
            "confidence": "context",
            "total_frontage_ft": round(permissive_all_total, 2),
            "road_count": len(permissive_all),
            "roads": permissive_all
        },
        
        # Nearby roads for context
        "nearby_roads": {
            "description": "All roads within 1000ft (for LLM context)",
            "count": len(nearby),
            "roads": nearby[:20]  # Limit to 20 nearest
        },
        
        # Summary for LLM
        "llm_context": {
            "has_strict_frontage": strict_total > 0,
            "has_moderate_frontage": moderate_total > 0,
            "has_permissive_frontage": permissive_public_total > 0,
            "has_any_road_access": permissive_all_total > 0,
            "nearest_public_road_distance": min([r['distance_ft'] for r in nearby if r['road_type'] in ['Secondary Highway', 'Local Road']], default=None),
            "nearest_any_road_distance": min([r['distance_ft'] for r in nearby], default=None) if nearby else None,
            "data_quality_note": "Large gaps (>100ft) between parcel and road may indicate shapefile accuracy issues"
        }
    })

@app.route('/calculate-frontage', methods=['POST'])
def calculate_frontage():
    """Legacy endpoint - kept for backward compatibility"""
    data = request.get_json()
    parcel_id = data.get('parcel_id')
    tolerance = data.get('tolerance', 30)
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
    frontages = calculate_frontage_with_tolerance(parcel_geom, tolerance, include_private)
    total = sum(r['frontage_ft'] for r in frontages)
    address = f"{parcel.get('situs_num', '')} {parcel.get('situs_stre', '')}, {parcel.get('situs_city', '')} {parcel.get('situs_zip', '')}".strip()
    
    return jsonify({
        "parcel_id": parcel_id,
        "normalized_id": normalized_id,
        "address": address,
        "total_frontage_ft": round(total, 2),
        "road_count": len(frontages),
        "roads": frontages,
        "tolerance_ft": tolerance,
        "include_private": include_private
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
