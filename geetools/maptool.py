# coding=utf-8

''' This module is designed to use in the Jupyter Notebook. It uses folium and
branca, and is inspired in https://github.com/mccarthyryanc/folium_gee '''
from __future__ import print_function
import folium
from folium import features
import ee
from copy import copy
from . import tools
import json

if not ee.data._initialized: ee.Initialize()


class Map(folium.Map):

    def __init__(self, **kwargs):
        super(Map, self).__init__(**kwargs)
        self.added_geometries = 0

    def show(self):
        LC = folium.LayerControl()
        self.add_child(LC)
        return self

    def addMarker(self, point, visParams=None, data=None, scale=None):
        """ Adds a marker with a popup given the data from an Image if
        data param is specified

        :param point: point
        :type point: ee.Geometry or ee.Feature
        :param visParams: visualization parameters
        :type visParams: dict
        :param data: Image from where to get the data from
        :type data: ee.Image
        :return:
        """
        if isinstance(point, ee.Geometry):
            geometry = point
        elif isinstance(point, ee.Feature):
            geometry = point.geometry()

        info = geometry.getInfo()
        type = info['type']
        coords = info['coordinates']
        coords = inverse_coordinates(coords)

        if data:
            # Try to get the image scale
            scale = data.projection().nominalScale().getInfo() if not scale else scale

            # Reduce if computed scale is too big
            scale = 1 if scale > 500 else scale

            values = tools.get_value(data, geometry, scale, 'client')
            val_str = ''
            for key, val in values.iteritems():
                val_str += '<b>{}:</b> {}</br>'.format(key, val)
                marker = folium.Marker(location=coords,
                                       popup=folium.Popup(val_str))
        else:
            marker = folium.Marker(location=coords)

        self.add_child(marker)

    def addLayer(self, eeObject, visParams=None, name=None, show=True,
                 opacity=None, inspect={'data':None, 'reducer':None, 'scale':None}):
        """
        Adds a given EE object to the map as a layer.

        Returns the new map layer.

        Arguments:
        eeObject (Collection|Feature|Image|MapId):
            The object to add to the map.

        visParams (FeatureVisualizationParameters|ImageVisualizationParameters,
        optional):
            The visualization parameters. For Images and ImageCollection,
            see ee.data.getMapId for valid parameters. For Features and
            FeatureCollections, the only supported key is "color",
            as a CSS 3.0 color string or a hex string in "RRGGBB" format.

        name (String, optional):
            The name of the layer. Defaults to "Layer N".

        shown (Boolean, optional):
            A flag indicating whether the layer should be on by default.

        opacity (Number, optional):
            The layer's opacity represented as a number between 0 and 1.
            Defaults to 1.

        Returns: ui.Map.Layer
        """
        thename = name
        def do_image(image):
            # image = eeObject

            name = thename if thename else image.id().getInfo()

            params = visParams if visParams else {}

            if params:
                got_default = params.has_key('bands') \
                              and params.has_key('min') \
                              and params.has_key('max')
            else:
                got_default = False

            # Default parameters
            if not got_default:
                default = get_default_vis(image)
                params.update(default)
            else:
                default = {}
                default.update(params)
                params = default

            # Take away bands from parameters
            newVisParams = {}
            for key, val in params.iteritems():
                if key == 'bands': continue
                newVisParams[key] = val

            # Get the MapID and Token after applying parameters
            image_info = image.select(params['bands']).getMapId(newVisParams)
            mapid = image_info['mapid']
            token = image_info['token']

            tiles = "https://earthengine.googleapis.com/map/%s/{z}/{x}/{y}?token=%s"%(mapid,token)
            folium_kwargs = {'attr': 'Map Data &copy; <a href="https://earthengine.google.com/">Google Earth Engine</a> ',
                             'tiles': tiles,
                             'name': name,
                             'overlay': True,
                             # 'show': show
                             }

            layer = folium.TileLayer(**folium_kwargs)
            layer.add_to(self)

            return self

        def do_geometry(geometry):
            info = geometry.getInfo()
            type = info['type']

            gjson_types = ['Polygon', 'LineString', 'MultiPolygon',
                           'LinearRing', 'MultiLineString', 'MultiPoint',
                           'Point', 'Polygon', 'Rectangle',
                           'GeometryCollection']

            newname = thename if thename else "{} {}".format(type, self.added_geometries)

            if type in gjson_types:
                data = inspect['data']
                red = inspect.get('reducer','first')
                sca = inspect.get('scale', None)
                popval = get_data(geometry, data, red, sca) if data else type

                layer = features.GeoJson(json.dumps(geometry.getInfo()),
                                         name=newname)
                pop = folium.Popup(popval)

                layer.add_child(pop)

                self.added_geometries += 1
                self.add_child(layer)
            else:
                print('unrecognized object type to add to map')

        # CASE: ee.Image
        if isinstance(eeObject, ee.Image):
            do_image(eeObject)

        elif isinstance(eeObject, ee.Geometry):
            do_geometry(eeObject)

        elif isinstance(eeObject, ee.Feature):
            print('feature')
            geom = eeObject.geometry()
            do_geometry(geom)

        elif isinstance(eeObject, ee.ImageCollection):
            pass
        else:
            raise ValueError('addLayer currently supports ee.Image as eeObject argument')

    def centerObject(self, object, zoom=None):
        """
        Centers the map view on a given object.

        Returns the map.

        Arguments:
        object (Element|Geometry):
        An object to center on - a geometry, image or feature.

        zoom (Number, optional):
        The zoom level, from 1 to 24. If unspecified, computed based on the object's bounding box.
        :return:
        """
        if isinstance(object, list):
            bounds = object
        else:
            # Make a buffer if object is a Point
            if isinstance(object, ee.Geometry):
                t = object.type().getInfo()
                if t == 'Point':
                    object = object.buffer(1000)

            bounds = tools.getRegion(object, True)

        # Catch unbounded images
        unbounded = [[[-180.0, -90.0], [180.0, -90.0],
                      [180.0, 90.0], [-180.0, 90.0],
                      [-180.0, -90.0]]]

        if bounds == unbounded:
            print("can't center object because it is unbounded")

        bounds = inverse_coordinates(bounds)
        self.fit_bounds([bounds[0], bounds[2]], max_zoom=zoom)

        return self

def get_default_vis(image, stretch=0.8):
    bandnames = image.bandNames().getInfo()

    if len(bandnames) < 3:
        selected = image.select([0]).getInfo()
        bandnames = bandnames[0]
    else:
        selected = image.select([0, 1, 2]).getInfo()
        bandnames = [bandnames[0], bandnames[1], bandnames[2]]

    bands = selected['bands']
    # bandnames = [bands[0]['id'], bands[1]['id'], bands[2]['id']]
    types = bands[0]['data_type']

    maxs = {'float':1,
            'double': 1,
            'int8': 127, 'uint8': 255,
            'int16': 32767, 'uint16': 65535,
            'int32': 2147483647, 'uint32': 4294967295,
            'int64': 9223372036854776000}

    precision = types['precision']

    if precision == 'float':
        btype = 'float'
    elif precision == 'double':
        btype = 'double'
    elif precision == 'int':
        max = types['max']
        maxs_inverse = dict((val, key) for key, val in maxs.iteritems())
        btype = maxs_inverse[int(max)]
    else:
        raise ValueError('Unknown data type {}'.format(precision))

    limits = {'float': 0.8}

    for key, val in maxs.iteritems():
        limits[key] = val*stretch

    min = 0
    max = limits[btype]
    return {'bands':bandnames, 'min':min, 'max':max}

def inverse_coordinates(coords):
    proxy = copy(coords)
    if isinstance(proxy, list):
        nest = -1
        ty = type(proxy)
        while ty == list:
            proxy = proxy[0]
            ty = type(proxy)
            nest += 1
    else:
        raise ValueError('coords must be at least a list of points')

    # Unnest
    if nest > 1:
        for n in range(nest-1):
            coords = coords[0]

    if nest > 0:
        newcoords = []
        for coord in coords:
            newcoord = [coord[1], coord[0]]
            newcoords.append(newcoord)

        # Nest again? NO

        return newcoords
    else:
        return [coords[1], coords[0]]

# TODO: Multiple dispatch! https://www.artima.com/weblogs/viewpost.jsp?thread=101605
def get_data(geometry, obj, reducer='first', scale=None):
    accepted = (ee.Image, ee.ImageCollection, ee.Feature, ee.FeatureCollection)

    reducers = {'first': ee.Reducer.first(),
                'mean': ee.Reducer.mean(),
                'median': ee.Reducer.median(),
                'sum':ee.Reducer.sum()}

    if not isinstance(obj, accepted):
        return "Can't get data from that Object"
    elif isinstance(obj, ee.Image):
        t = geometry.type().getInfo()
        # Try to get the image scale
        scale = obj.select([0]).projection().nominalScale().getInfo()\
                if not scale else scale

        # Reduce if computed scale is too big
        scale = 1 if scale > 500 else scale
        if t == 'Point':
            values = tools.get_value(obj, geometry, scale, 'client')
            val_str = ''
            for key, val in values.iteritems():
                val_str += '<b>{}:</b> {}</br>'.format(key, val)
            return val_str
        elif t == 'Polygon':
            red = reducer if reducer in reducers.keys() else 'first'
            values = obj.reduceRegion(reducers[red], geometry, scale, maxPixels=1e13).getInfo()
            val_str = '<h3>{}:</h3>\n'.format(red)
            for key, val in values.iteritems():
                val_str += '<b>{}:</b> {}</br>'.format(key, val)
            return val_str