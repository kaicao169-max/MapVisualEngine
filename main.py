# %%
import json
from loguru import logger
from engine import VisualEngine, MapConfig
# %%
def run_pipeline(class_params_path):
    try:
        with open(class_params_path, 'r', encoding='utf-8') as f:
            class_params = json.load(f)
            logger.info(f"配置加载成功，数据路径为: {class_params.get('data_path')}")
    except (FileNotFoundError, KeyError) as e:
        logger.error(f"文件读取错误！| {type(e).__name__}: {e}")
    
    config = MapConfig.from_dict(class_params)

    visualengine = VisualEngine(config)
    gdf = visualengine.load_and_simplify()
    m = visualengine.auto_fit_map(
        map_mode="dark_mode",
        zoom_start=11,
        match_phone_str='<meta name="viewport" content="width=device-width, initial-scale=1.0">')
    visualengine.load_resources()
    visualengine.add_popup_marker_to_m(
        'status', 
        'id',
        ['geometry'], 
        10, 
        '监测点')
    visualengine.add_geojson_to_m('status', ['id', 'class'], ['id', 'value'], map_name='geojson层')
    visualengine.add_legend_to_m()
    visualengine.finalize_map(False)
    final_m = visualengine.m
    return final_m
# %%
if __name__ == "__main__":
    final_m = run_pipeline(r'D:\python_workspace\Australia_dream\MapVisualEngine\config\CLASS_PARAMS.json')
    final_m.save("test_map.html")
# %%
