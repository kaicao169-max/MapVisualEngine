# %%
import json
import branca
import folium
from dataclasses import dataclass, fields
from folium.plugins import MarkerCluster
from typing import Optional, Union, Any
import geopandas as gpd
from loguru import logger
from branca.element import MacroElement
from jinja2 import Template
# %%
"""
1. @dataclass 装饰器是什么？
在 Python 里，如果想定义一个类用来存数据，
通常要写一大堆冗长的 __init__ 函数，把每个属性手动赋值一遍。

加了 @dataclass 后：只需要声明变量名字和类型（比如 data_path: str）。
Python 运行的时候，会自动帮你补全那个繁琐的 __init__ 函数。
"""
@dataclass
class MapConfig:
    data_path: str
    config_path: str
    default_tiles: str
    popup_html_path: str
    popup_style_path: str
    marker_style_path: str
    legend_html_path: str
    legend_style_path: str

    def __post_init__(self):
        # 这是一个自动检查器，一旦你创建对象，它会自动跑
        # 如果发现有字段没填或者填了空字符串，它直接抛错，让你立刻知道哪不对
        # fields 是从 dataclasses 导入的一个函数
        for field in fields(self):
            value = getattr(self, field.name)
            if not value:
                raise ValueError(f"❌ 配置错误：字段 '{field.name}' 不能为空！")

    """
    @classmethod：
    这表示“这个方法属于类本身”，不需要创建对象就能调用它。
    直接写 MapConfig.from_dict(...) 就行。

    定义时写了 @classmethod 和 cls 参数：
    from_dict(cls, d)：当你写 MapConfig.from_dict(...) 时，
    Python 会自动把 MapConfig 这个类当做第一个参数 cls 传进去。

    cls：这其实就是 MapConfig 这个类。
    d：这是 Python 的字典解包语法。
        假设读取的 JSON 内容是 d = {'data_path': 'a.json', 'config_path': 'b.json'}。
        当写 cls(d) 时，Python 会自动翻译成：MapConfig(data_path='a.json', config_path='b.json')。
    """
    @classmethod
    def from_dict(cls, d):
        return cls(**d)
# %%
class ResourceInjector(MacroElement):
    """
    独立注入器：专门负责把 CSS/JS/HTML 安全地塞进 folium 地图中。
    """
    def __init__(self, content, resource_type='html'):
        super(ResourceInjector, self).__init__()
        """
        macro (宏)：你可以把它理解为 “预留好的函数”。
            Folium 渲染地图时，会按顺序调用这些函数（header, script, html）。
        
        header、script、html 的特殊身份：
            这是 Folium 专门为了往 HTML 网页的 <head>、<script>或<html> 标签里塞代码而设计的“快捷通道”。

        if type == 'css'：这就是你在做“筛选”。

        {% macro header(this, kwargs) %}: 1. 声明：这是给 <head> 区域准备的“模板插槽”
        {% if type == 'css' %}{{ content }}{% endif %}:  2. 判断：如果是 CSS 类型，就把内容放进去
        {% endmacro %}: 3. 结束：该插槽定义完毕
        """
        self._template = Template("""
            {% macro header(this, kwargs) %}                     
                {% if type == 'css' %}{{ content }}{% endif %}   
            {% endmacro %}                               
            {% macro script(this, kwargs) %}
                {% if type == 'js' %}<script>{{ content }}</script>{% endif %}
            {% endmacro %}
            {% macro html(this, kwargs) %}
                {% if type == 'html' %}{{ content }}{% endif %}
            {% endmacro %}
        """)
        self._template.module.content = content
        self._template.module.type = resource_type
# %%
class VisualEngine:
    """
    环境数据可视化引擎
    使用方式：
    1. 首先传入gdf数据、配置文件、底图、标记和弹窗html文件路径。
    2. 调用 load_and_simplify(...) 读取gdf，并根据需要选择是否需要简化gdf。
    3. 调用 auto_fit_map(...) ，根据gdf的几何形状获取质心，并将底图层加入folium中。
    4. 调用 load_resources(...) 读取配置文件，标记和弹窗所需的html文件。
    5. 调用 generate_icon(...) 和 generate_popup(...) 生成所需标记和弹窗。
    6. 调用 add_popup_marker_to_m(...) 将生成的标记和弹窗内容加载到folium中。
    7. 调用 _get_geojson_config(...) 生成geojson所需参数，并使用add_geojson_to_m(...)将渲染的几何形状添加到folium中。
    8. 调用finalize_map(...)在地图渲染各个步骤完成后给地图添加图层开关。
    """
    def __init__(self, config: MapConfig) -> None:

        # 以后直接调用 config.data_path，比写 kwargs.get('data_path') 快多了
        self.config = config 
        # ... 原有的其他初始化逻辑保持不变
        
        self.gdf: Optional[gpd.GeoDataFrame] = None
        self.marker_template: Optional[str]  = None
        self.legend_template: Optional[str]  = None
        self.popup_template: Optional[str] = None
        self.legend_html: Optional[str] = None
        self.popup_html: Optional[str] = None
        self.m: Optional[folium.Map] = None
        self.CONFIG: dict = {}

        self._is_map_ready = False
        self._is_gdf_ready = False
        self._is_resources_ready = False
        self._is_geojson_style_ready = False


    def load_and_simplify(self, tolerance: Optional[int]=None) -> Optional[gpd.GeoDataFrame]:
        data_path = self.config.data_path

        try:
            self.gdf = gpd.read_file(data_path)
            logger.info("✔️已成功读取目标gdf文件！")
        except (FileNotFoundError, KeyError) as e:
            self._is_gdf_ready = False
            logger.error(f'data_path出错，找不到文件！| {type(e).__name__}: {e}')
            return None
        
        if tolerance is not None:
            self.gdf = self.gdf.simplify(tolerance=tolerance, preserve_topology=True)
            logger.info(f"✅ 已应用简化处理 (tolerance={tolerance})")
        else:
            logger.info("ℹ️ 未进行简化处理，使用原始精度")

        self._is_gdf_ready = True

        return self.gdf
    

    def auto_fit_map(
        self, 
        map_mode: str=None,
        zoom_start: Optional[int]=None,
        match_phone_str: str=None
    ) -> Optional[folium.Map]:
        if not self._is_gdf_ready:
            raise RuntimeError("❌ 引擎未就绪：请先调用 load_and_simplify() 加载数据。")
        
        if self.gdf.empty:
            logger.error(f'❌self.gdf是空的，没有任何内容，请重新检查！。')
            return None
        
        # 1. 计算所有形状的覆盖范围 [minx, miny, maxx, maxy]
        bounds = self.gdf.total_bounds

        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2

        # 1. 设定一个默认的底图配置 (防止后续没数据可用)
        map_config = {"Default": "OpenStreetMap"}

        default_tiles = self.config.default_tiles

        try: 
            with open(default_tiles, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if data:
                    map_config = data
                    logger.info('✅ 成功加载外部底图配置')
        except Exception as e:
            logger.warning(f"⚠️ 无法加载外部底图配置，启用默认模式: {e}")
        
        map_dict = map_config.get(map_mode)
        if map_dict:
            m = folium.Map(
                location=[center_lat, center_lon], 
                zoom_start=zoom_start, 
                tiles=None
            )

            folium.TileLayer(
                tiles=map_dict.get("url", "OpenStreetMap"),
                attr=map_dict.get("attr", "未知"),
                name=map_dict.get("name", "默认底图") # 给它起个好听的名字！
            ).add_to(m)

            for mode_name, map_dict in map_config.items():
                if mode_name == map_mode:
                    continue
                else:
                    folium.TileLayer(
                        tiles=str(map_dict.get("url", "OpenStreetMap")), 
                        attr=str(map_dict.get("attr", "未知")),
                        name=str(map_dict.get("name", "未知"))
                    ).add_to(m)

        # 2. 转换为 Folium 要求的格式 [[min_y, min_x], [max_y, max_x]]
        # 也就是左下角和右上角的坐标点
        bbox = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]
        m.fit_bounds(bbox)

        m.get_root().header.add_child(branca.element.Element(match_phone_str))
        self.m = m
        logger.info(f"✅ 地图视窗已自动聚焦: {bbox}")
        self._is_map_ready = True

        return m
    

    def _load_config(self) -> None:
        """在这里进行读取，统一处理路径与异常"""
        config_path = self.config.config_path
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.CONFIG = json.load(f)
        except FileNotFoundError:
            logger.error(f"找不到配置文件: {config_path}")
        except json.JSONDecodeError:
            logger.error(f"配置文件格式有误: {config_path}")

    def _load_marker_styles(self) -> None:
        marker_style_path = self.config.marker_style_path
        
        try:
            with open(marker_style_path, 'r', encoding='utf-8') as f:
                self.marker_template = f.read()
            self.m.get_root().header.add_child(branca.element.Element(self.marker_template))
            logger.info("✅ 标记样式模板已成功注入到地图")
        except Exception as e:
            logger.error(f"❌ 样式模板读取失败: {e}")

    def _load_popup_html(self) -> None:
        popup_html_path = self.config.popup_html_path
        
        try:
            with open(popup_html_path, 'r', encoding='utf-8') as f:
                self.popup_html = f.read()
            logger.info("✅ 弹窗文本模板已成功读取！")
        except Exception as e:
            logger.error(f"❌ 弹窗文本模板读取失败: {e}")

    def _load_popup_styles(self) -> None:
        popup_style_path = self.config.popup_style_path
        
        try:
            with open(popup_style_path, 'r', encoding='utf-8') as f:
                self.popup_template = f.read()
            self.m.add_child(ResourceInjector(self.popup_template, 'html'))
            logger.info("✅ 弹窗样式模板已成功注入到地图")
        except Exception as e:
            logger.error(f"❌ 样式模板读取失败: {e}")

    def _load_legend_styles(self) -> None:
        legend_style_path = self.config.legend_style_path
        
        try:
            with open(legend_style_path, 'r', encoding='utf-8') as f:
                self.legend_template = f.read()
            self.m.get_root().header.add_child(branca.element.Element(self.legend_template))
            logger.info("✅ 图例样式已成功读取！")
        except Exception as e:
            logger.error(f"❌ 样式模板读取失败: {e}")

    def _load_legend_html(self) -> None:
        legend_html_path = self.config.legend_html_path
        
        try:
            with open(legend_html_path, 'r', encoding='utf-8') as f:
                self.legend_html = f.read()
            logger.info("✅ 图例样式已成功读取！")
        except Exception as e:
            logger.error(f"❌ 样式模板读取失败: {e}")

    def load_resources(self) -> None:
        if not self._is_map_ready:
            raise RuntimeError("必须先执行 auto_fit_map 生成地图，才能加载样式！")
        
        try:
            self._load_config()
            self._load_marker_styles()
            self._load_popup_html()
            self._load_popup_styles()
            self._load_legend_styles()
            self._load_legend_html()

            self._is_resources_ready = True
            logger.info('🎇配置和样式文件已加载完毕！')
        except Exception as e:
            self._is_resources_ready = False
            logger.error(f"❌ 资源加载流水线中断: {e}")
            raise # 向上层抛出，让使用者知道加载没成功

    
    def _get_fallback_marker(self) -> folium.Icon:
        """兜底弹窗：当骨架加载失败或为空时调用"""
        logger.warning("⚠️ 标记未就绪，启用降级简易标记。")
        # 简单拼接一个字符串，不依赖外部文件
        icon = folium.Icon(color='blue', icon='info_sigh')
        return icon
    
    def generate_icon(self, row: Any, col_name: str) -> Union[folium.DivIcon, folium.Icon]:
        if not self._is_resources_ready:
            raise RuntimeError("必须先完成 load_resources 才能生成图标！")
        
        if not self.CONFIG:
            icon = self._get_fallback_marker()
            logger.info(f'配置文件中什么都没有，使用默认标记！')
            return icon
        else:
            map_config = self.CONFIG.get(row[col_name])
            hex_color = map_config.get('color', '#ff0000')
            rgba_color = map_config.get("rgba_color", "rgba(231, 76, 60, 0.5)")
            duration = map_config.get('duration', '2s')
            icon_size = map_config.get("icon_size", (16, 16))
            icon_anchor = map_config.get("icon_anchor", (6, 6))
            blur_radius = map_config.get("blur", '5px')
            spread_radius = map_config.get("spread", '25px')

        html_content = f"""
            <div class="my-pulse" style="
                --bg-color: {hex_color}; 
                --shadow-color: {rgba_color}; 
                --anim-dur: {duration};
                --blur-radius: {blur_radius};
                --spread-radius: {spread_radius};
            "></div>
            """
        
        icon = folium.DivIcon(
            html=html_content,
            icon_size=icon_size,
            icon_anchor=icon_anchor
        )

        return icon
    
    def _get_fallback_popup(self, row: Any, info_col_name: str) -> folium.Popup:
        """兜底弹窗：当骨架加载失败或为空时调用"""
        logger.warning("⚠️ 弹窗骨架未就绪，启用降级简易弹窗。")
        # 简单拼接一个字符串，不依赖外部文件
        fallback_html = f"<div>站点: {row.get(info_col_name, '未知')}</div>"
        return folium.Popup(html=fallback_html, max_width=300, parse_html=True)
    
    def generate_popup(self, row: Any, col_name: str, info_col_name: str) -> folium.Popup:
        if not self._is_resources_ready:
            raise RuntimeError("必须先完成 load_resources 才能生成图标！")

        if not self.popup_html:
            return self._get_fallback_popup(row, info_col_name)
        
        if self.CONFIG:
            config = self.CONFIG.get(row[col_name])
            color = config.get('color', "#e74c3c")
            style_str = f'style="background-color: {color} !important;"'
            html_content = self.popup_html.format(extra_style=style_str, **row.to_dict())
        else:
            html_content = self.popup_html.format(**row.to_dict())
        #     html_content = html_content.replace(
        #         '<span class="status-normal">',
        #         f'<span class="status-normal" style="background-color: {color} !important;">')
        # else:
        #     config = self.CONFIG.get(row[col_name])
        #     color = config.get('color', "#e74c3c")
        #     html_content = f'''
        #         <div class="status-normal" style="
        #             background-color: {color} !important;">
        #         </div>''' + self.popup_html.format(**row.to_dict())
        
        """
        IFrame 是绕过这个“解析与转义”过程的终极手段：
        非解析对象：IFrame 对象在 Folium 内部不被视为需要解析的字符串，而是一个独立的资源容器。
        原生注入：Folium 看到 IFrame 对象时，会直接将其作为 <iframe> 标签插入，
            根本不会去检查里面的内容是否有 HTML 标签或引号，从而彻底避免了 Folium 自动转义逻辑的干扰。
        """
        iframe = folium.IFrame(html=html_content, width=250, height=150)
        popup = folium.Popup(html=iframe, max_width=300)

        return popup
    

    def add_popup_marker_to_m(
        self, 
        col_name: str, 
        info_col_name: str,
        drop_columns: list[str],
        number_limit: int,
        layer_name: str
    ) -> None:

        locations = [[geom.centroid.y, geom.centroid.x] for geom in self.gdf.geometry]
        new_gdf = self.gdf.drop(columns=drop_columns, errors='ignore').copy()

        if new_gdf.empty:
            logger.warning("警告：无有效数据可绘制。")
            return

        # 1. 创建一个组，给这个组起名字 (这个名字会显示在图层控制面板里)
        marker_group = folium.FeatureGroup(name=layer_name).add_to(self.m)
        if len(self.gdf) > number_limit:
            container = MarkerCluster().add_to(marker_group)
        else:
            container = marker_group

        for i, (_, row) in enumerate(new_gdf.iterrows()):

            popup = self.generate_popup(row, col_name, info_col_name)
            marker = self.generate_icon(row, col_name)

            folium.Marker(
                location=locations[i],
                icon=marker,
                popup=popup
            ).add_to(container)
        

    def _get_geojson_config(
        self, 
        col_name: str,
        tooltip_columns: list[str],
        popup_columns: list[str]
    ) -> dict:
        if not self._is_resources_ready:
            raise RuntimeError("配置文件还未加载，请先执行load_resources方法！")
        
        def style_func(feature):
            status = feature['properties'].get(col_name)
            config = self.CONFIG.get(status, {})
            return {
                'fillColor': config.get('color', '#808080'),
                'color': 'white',
                'weight': 1,
                'fillOpacity': config.get('fillOpacity', 0.4)
            }

        return {
            'style_function': style_func,
            'highlight_function': lambda x: {'weight': 3, 'color': 'black', 'fillOpacity': 0.6},
            'tooltip': folium.GeoJsonTooltip(fields=tooltip_columns, localize=True),
            'popup': folium.GeoJsonPopup(fields=popup_columns, localize=True)
        }
    
    def add_geojson_to_m(
        self, 
        col_name: str,
        tooltip_columns: list[str],
        popup_columns: list[str],
        map_name: str=None
    ) -> None:
        if not self._is_map_ready:
            raise RuntimeError("地图还未加载，请先执行 auto_fit_map 方法！")
        
        config = self._get_geojson_config(col_name, tooltip_columns, popup_columns)

        folium.GeoJson(
            self.gdf,
            name=map_name,
            **config
        ).add_to(self.m)


    def add_legend_to_m(self, ):
        if not self._is_map_ready or not self._is_resources_ready:
            raise RuntimeError("地图还未加载或相关配置尚未加载！")
        
        if self.CONFIG is not None and len(self.CONFIG) > 0:
            # 1. 先用模板初始化
            legend_html = self.legend_html

            for config in self.CONFIG.values():
                color = config.get("color", "#e74c3c")
                label = config.get("label", "危险")
                
                legend_html += f"""
                <div class="legend-row" style="--box-color: {color}";>
                    <i class="legend-color-box"></i>
                    <span class="legend-font">{label}</span>
                </div>
                """
            legend_html += '</div>'
            self.m.get_root().html.add_child(branca.element.Element(legend_html))
        else:
            logger.info("配置文件没有内容，无法实现添加图例的操作！")


    def finalize_map(self, choice: bool=False) -> None:
        """
        终极收尾函数：
        1. 确保所有图层被正确注册
        2. 最后添加 LayerControl，避免重复面板
        3. 返回最终准备好的地图对象
        """
        folium.LayerControl(collapsed=choice).add_to(self.m)
        return self.m

# %%
