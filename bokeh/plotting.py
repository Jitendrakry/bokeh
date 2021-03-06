from __future__ import print_function

import logging
logger = logging.getLogger(__name__)

import io
import itertools
import os
import re
import time
import warnings

from six import string_types

from . import browserlib
from . import _glyph_functions as gf
from .deprecate import deprecated
from .document import Document
from .embed import notebook_div, file_html, autoload_server
from .models import (
    Axis, FactorRange, Grid, GridPlot, HBox, Legend, LogAxis, Plot, Tool, VBox, Widget
)
from .palettes import brewer
from .plotting_helpers import (
    get_default_color, get_default_alpha, _handle_1d_data_args, _list_attr_splat,
    _get_range, _get_axis_class, _get_num_minor_ticks, _tool_from_string
)
from .resources import Resources
from .session import DEFAULT_SERVER_URL, Session
from .utils import decode_utf8, publish_display_data

# extra imports -- just things to add to 'from plotting import *'
from bokeh.models import ColumnDataSource

_default_document = Document()

_default_session = None

_default_file = None

_default_notebook = None

DEFAULT_TOOLS = "pan,wheel_zoom,box_zoom,save,resize,reset"

class Figure(Plot):
    __subtype__ = "Figure"
    __view_model__ = "Plot"

    def __init__(self, *arg, **kw):

        tools = kw.pop("tools", DEFAULT_TOOLS)

        x_range = kw.pop("x_range", None)
        y_range = kw.pop("y_range", None)

        x_axis_type = kw.pop("x_axis_type", "auto")
        y_axis_type = kw.pop("y_axis_type", "auto")

        x_minor_ticks = kw.pop('x_minor_ticks', 'auto')
        y_minor_ticks = kw.pop('y_minor_ticks', 'auto')

        x_axis_location = kw.pop("x_axis_location", "below")
        y_axis_location = kw.pop("y_axis_location", "left")

        x_axis_label = kw.pop("x_axis_label", "")
        y_axis_label = kw.pop("y_axis_label", "")

        super(Figure, self).__init__(*arg, **kw)

        self.x_range = _get_range(x_range)
        self.y_range = _get_range(y_range)

        x_axiscls = _get_axis_class(x_axis_type, self.x_range)
        if x_axiscls:
            if x_axiscls is LogAxis:
                self.x_mapper_type = 'log'
            xaxis = x_axiscls(plot=self)
            xaxis.ticker.num_minor_ticks = _get_num_minor_ticks(x_axiscls, x_minor_ticks)
            axis_label = x_axis_label
            if axis_label:
                xaxis.axis_label = axis_label
            xgrid = Grid(plot=self, dimension=0, ticker=xaxis.ticker)
            if x_axis_location == "above":
                self.above.append(xaxis)
            elif x_axis_location == "below":
                self.below.append(xaxis)

        y_axiscls = _get_axis_class(y_axis_type, self.y_range)
        if y_axiscls:
            if y_axiscls is LogAxis:
                self.y_mapper_type = 'log'
            yaxis = y_axiscls(plot=self)
            yaxis.ticker.num_minor_ticks = _get_num_minor_ticks(y_axiscls, y_minor_ticks)
            axis_label = y_axis_label
            if axis_label:
                yaxis.axis_label = axis_label
            ygrid = Grid(plot=self, dimension=1, ticker=yaxis.ticker)
            if y_axis_location == "left":
                self.left.append(yaxis)
            elif y_axis_location == "right":
                self.right.append(yaxis)

        tool_objs = []
        temp_tool_str = ""

        if isinstance(tools, (list, tuple)):
            for tool in tools:
                if isinstance(tool, Tool):
                    tool_objs.append(tool)
                elif isinstance(tool, string_types):
                    temp_tool_str += tool + ','
                else:
                    raise ValueError("tool should be a string or an instance of Tool class")
            tools = temp_tool_str

        # Remove pan/zoom tools in case of categorical axes
        remove_pan_zoom = (isinstance(self.x_range, FactorRange) or
                           isinstance(self.y_range, FactorRange))

        repeated_tools = []
        removed_tools = []

        for tool in re.split(r"\s*,\s*", tools.strip()):
            # re.split will return empty strings; ignore them.
            if tool == "":
                continue

            if remove_pan_zoom and ("pan" in tool or "zoom" in tool):
                removed_tools.append(tool)
                continue

            tool_obj = _tool_from_string(tool)
            tool_obj.plot = self

            tool_objs.append(tool_obj)

        self.tools.extend(tool_objs)

        for typename, group in itertools.groupby(sorted([ tool.__class__.__name__ for tool in self.tools ])):
            if len(list(group)) > 1:
                repeated_tools.append(typename)

        if repeated_tools:
            warnings.warn("%s are being repeated" % ",".join(repeated_tools))

        if removed_tools:
            warnings.warn("categorical plots do not support pan and zoom operations.\n"
                          "Removing tool(s): %s" %', '.join(removed_tools))


    def _axis(self, *sides):
        objs = []
        for s in sides:
            objs.extend(getattr(self, s, []))
        axis = [obj for obj in objs if isinstance(obj, Axis)]
        return _list_attr_splat(axis)

    @property
    def xaxis(self):
        """ Get the current `x` axis object(s)

        Returns:
            splattable list of x-axis objects on this Plot
        """
        return self._axis("above", "below")

    @property
    def yaxis(self):
        """ Get the current `y` axis object(s)

        Returns:
            splattable list of y-axis objects on this Plot
        """
        return self._axis("left", "right")

    @property
    def axis(self):
        """ Get all the current axis objects

        Returns:
            splattable list of axis objects on this Plot
        """
        return _list_attr_splat(self.xaxis + self.yaxis)

    @property
    def legend(self):
        """ Get the current :class:`legend <bokeh.models.Legend>` object(s)

        Returns:
            splattable list of legend objects on this Plot
        """
        legends = [obj for obj in self.renderers if isinstance(obj, Legend)]
        return _list_attr_splat(legends)

    def _grid(self, dimension):
        grid = [obj for obj in self.renderers if isinstance(obj, Grid) and obj.dimension==dimension]
        return _list_attr_splat(grid)

    @property
    def xgrid(self):
        """ Get the current `x` :class:`grid <bokeh.models.Grid>` object(s)

        Returns:
            splattable list of legend objects on this Plot
        """
        return self._grid(0)

    @property
    def ygrid(self):
        """ Get the current `y` :class:`grid <bokeh.models.Grid>` object(s)

        Returns:
            splattable list of y-grid objects on this Plot
        """
        return self._grid(1)

    @property
    def grid(self):
        """ Get the current :class:`grid <bokeh.models.Grid>` object(s)

        Returns:
            splattable list of grid objects on this Plot
        """
        return _list_attr_splat(self.xgrid + self.ygrid)

    annular_wedge     = gf.annular_wedge
    annulus           = gf.annulus
    arc               = gf.arc
    asterisk          = gf.asterisk
    bezier            = gf.bezier
    circle            = gf.circle
    circle_cross      = gf.circle_cross
    circle_x          = gf. circle_x
    cross             = gf.cross
    diamond           = gf.diamond
    diamond_cross     = gf.diamond_cross
    image             = gf.image
    image_rgba        = gf.image_rgba
    image_url         = gf.image_url
    inverted_triangle = gf.inverted_triangle
    line              = gf.line
    multi_line        = gf.multi_line
    oval              = gf.oval
    patch             = gf.patch
    patches           = gf.patches
    quad              = gf.quad
    quadratic         = gf.quadratic
    ray               = gf.ray
    rect              = gf.rect
    segment           = gf.segment
    square            = gf.square
    square_cross      = gf.square_cross
    square_x          = gf.square_x
    text              = gf.text
    triangle          = gf.triangle
    wedge             = gf.wedge
    x                 = gf.x

    def scatter(self, *args, **kwargs):
        """ Creates a scatter plot of the given x and y items.

        Args:
            *args : The data to plot.  Can be of several forms:

                (X, Y)
                    Two 1D arrays or iterables
                (XNAME, YNAME)
                    Two bokeh DataSource/ColumnsRef

            marker (str, optional): a valid marker_type, defaults to "circle"
            color (color value, optional): shorthand to set both fill and line color

        All the :ref:`userguide_objects_line_properties` and :ref:`userguide_objects_fill_properties` are
        also accepted as keyword parameters.

        Examples:

            >>> p.scatter([1,2,3],[4,5,6], fill_color="red")
            >>> p.scatter("data1", "data2", source=data_source, ...)

        """
        ds = kwargs.get("source", None)
        names, datasource = _handle_1d_data_args(args, datasource=ds)
        kwargs["source"] = datasource

        markertype = kwargs.get("marker", "circle")

        # TODO: How to handle this? Just call curplot()?
        if not len(_color_fields.intersection(set(kwargs.keys()))):
            kwargs['color'] = get_default_color()
        if not len(_alpha_fields.intersection(set(kwargs.keys()))):
            kwargs['alpha'] = get_default_alpha()

        if markertype not in _marker_types:
            raise ValueError("Invalid marker type '%s'. Use markers() to see a list of valid marker types." % markertype)

        # TODO (bev) make better when plotting.scatter is removed
        conversions = {
            "*": "asterisk",
            "+": "cross",
            "o": "circle",
            "ox": "circle_x",
            "o+": "circle_cross"
        }
        if markertype in conversions:
            markertype = conversions[markertype]

        return getattr(self, markertype)(*args, **kwargs)

def curdoc():
    ''' Return the current document.

    Returns:
        doc : the current default document object.
    '''
    try:
        """This is used when we need to call the plotting API from within
        the server, within a request context.  (Applets do this for example)
        in this case you still want the API to work but you don't want
        to use the global module level document
        """
        from flask import request
        doc = request.bokeh_server_document
        logger.debug("returning config from flask request")
        return doc
    except (ImportError, RuntimeError, AttributeError):
        return _default_document

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure objects")
def curplot():
    ''' Return the current default plot object.

    Returns:
        plot : the current default plot (or None)
    '''
    return curdoc().curplot()

def cursession():
    ''' Return the current session, if there is one.

    Returns:
        session : the current default session object (or None)
    '''
    return _default_session

def reset_output():
    ''' Deactivate all currently active output modes.

    Subsequent calls to show() will not render until a new output mode is
    activated.

    Returns:
        None

    '''
    global _default_document
    global _default_session
    global _default_file
    global _default_notebook
    _default_document = Document()
    _default_session = None
    _default_file = None
    _default_notebook = None

@deprecated("Bokeh 0.7", "methods on bokeh.plotting.Figure objects")
def hold(value=True):
    ''' Set or clear the plot hold status on the current document.

    This is a convenience function that acts on the current document, and is equivalent to curdoc().hold(...)

    Args:
        value (bool, optional) : whether hold should be turned on or off (default: True)

    Returns:
        None
    '''
    curdoc().hold(value)

def figure(**kwargs):
    ''' Activate a new figure for plotting.

    All subsequent plotting operations will affect the new figure.

    This function accepts all plot style keyword parameters.

    Returns:
       figure : a new :class:`Plot <bokeh.models.plots.Plot>`

    '''
    fig = Figure(**kwargs)
    curdoc()._current_plot = fig
    curdoc().add(fig)
    return fig

def output_server(docname, session=None, url="default", name=None, clear=True):
    """ Cause plotting commands to automatically persist plots to a Bokeh server.

    Can use explicitly provided Session for persistence, or the default
    session.

    Args:
        docname (str) : name of document to push on Bokeh server
            An existing documents with the same name will be overwritten.
        session (Session, optional) : An explicit session to use (default: None)
            If session is None, use the default session
        url (str, optianal) : URL of the Bokeh server  (default: "default")
            if url is "default" use session.DEFAULT_SERVER_URL
        name (str, optional) :
            if name is None, use the server URL as the name
        clear (bool, optional) :
            should an existing server document be cleared of any existing
            plots. (default: True)

    Additional keyword arguments like **username**, **userapikey**,
    and **base_url** can also be supplied.

    Returns:
        None

    .. note:: Generally, this should be called at the beginning of an
              interactive session or the top of a script.

    .. note:: By default, calling this function will replaces any existing
              default Server session.

    """
    global _default_session
    if url == "default":
        url = DEFAULT_SERVER_URL
    if name is None:
        name = url
    if not session:
        if not _default_session:
            _default_session = Session(name=name, root_url=url)
        session = _default_session
    session.use_doc(docname)
    session.load_document(curdoc())
    if clear:
        curdoc().clear()

def output_notebook(url=None, docname=None, session=None, name=None,
                    force=False):
    if session or url or name:
        if docname is None:
            docname = "IPython Session at %s" % time.ctime()
        output_server(docname, url=url, session=session, name=name)
    else:
        from . import load_notebook
        load_notebook(force=force)
    global _default_notebook
    _default_notebook = True

def output_file(filename, title="Bokeh Plot", autosave=False, mode="inline", root_dir=None):
    """ Outputs to a static HTML file.

    .. note:: This file will be overwritten each time show() or save() is invoked.

    Args:
        autosave (bool, optional) : whether to automatically save (default: False)
            If **autosave** is True, then every time plot() or one of the other
            visual functions is called, this causes the file to be saved. If it
            is False, then the file is only saved upon calling show().

        mode (str, optional) : how to inlude BokehJS (default: "inline")
            **mode** can be 'inline', 'cdn', 'relative(-dev)' or 'absolute(-dev)'.
            In the 'relative(-dev)' case, **root_dir** can be specified to indicate the
            base directory from which the path to the various static files should be
            computed.

    .. note:: Generally, this should be called at the beginning of an
              interactive session or the top of a script.

    """
    global _default_file
    _default_file = {
        'filename'  : filename,
        'resources' : Resources(mode=mode, root_dir=root_dir),
        'autosave'  : autosave,
        'title'     : title,
    }

    if os.path.isfile(filename):
        print("Session output file '%s' already exists, will be overwritten." % filename)


def show(obj=None, browser=None, new="tab", url=None):
    """ 'shows' a plot object or the current plot, by auto-raising the window or tab
    displaying the current plot (for file/server output modes) or displaying
    it in an output cell (IPython notebook).

    Args:
        obj (Widget/Plot object, optional): it accepts a plot object and just shows it.

        browser (str, optional) : browser to show with (default: None)
            For systems that support it, the **browser** argument allows specifying
            which browser to display in, e.g. "safari", "firefox", "opera",
            "windows-default".  (See the webbrowser module documentation in the
            standard lib for more details.)

        new (str, optional) : new file output mode (default: "tab")
            For file-based output, opens or raises the browser window
            showing the current output file.  If **new** is 'tab', then
            opens a new tab. If **new** is 'window', then opens a new window.
    """
    filename = _default_file['filename'] if _default_file else None
    session = cursession()
    notebook = _default_notebook

    # Map our string argument to the webbrowser.open argument
    new_param = {'tab': 2, 'window': 1}[new]

    controller = browserlib.get_browser_controller(browser=browser)
    if obj is None:
        if notebook:
            plot = curplot()
        else:
            plot = curdoc()
    else:
        plot = obj
    if not plot:
        warnings.warn("No current plot to show. Use renderer functions (circle, rect, etc.) to create a current plot (see http://bokeh.pydata.org/index.html)")
        return
    if notebook and session:
        push(session=session)
        snippet = autoload_server(plot, cursession())
        publish_display_data({'text/html': snippet})

    elif notebook:
        publish_display_data({'text/html': notebook_div(plot)})

    elif session:
        push()
        if url:
            controller.open(url, new=new_param)
        else:
            controller.open(session.object_link(curdoc().context))

    elif filename:
        save(filename, obj=plot)
        controller.open("file://" + os.path.abspath(filename), new=new_param)


def save(filename=None, resources=None, obj=None, title=None):
    """ Updates the file with the data for the current document.

    If a filename is supplied, or output_file(...) has been called, this will
    save the plot to the given filename.

    Args:
        filename (str, optional) : filename to save document under (default: None)
            if `filename` is None, the current output_file(...) filename is used if present
        resources (Resources, optional) : BokehJS resource config to use
            if `resources` is None, the current default resource config is used, failing that resources.INLINE is used

        obj (Document or Widget/Plot object, optional)
            if provided, then this is the object to save instead of curdoc()
            and its curplot()
        title (str, optional) : title of the bokeh plot (default: None)
        	if 'title' is None, the current default title config is used, failing that 'Bokeh Plot' is used

    Returns:
        None

    """
    if filename is None and _default_file:
        filename = _default_file['filename']

    if resources is None and _default_file:
        resources = _default_file['resources']

    if title is None and _default_file:
        title = _default_file['title']

    if not filename:
        warnings.warn("save() called but no filename was supplied and output_file(...) was never called, nothing saved")
        return

    if not resources:
        warnings.warn("save() called but no resources was supplied and output_file(...) was never called, defaulting to resources.INLINE")
        from .resources import INLINE
        resources = INLINE


    if not title:
        warnings.warn("save() called but no title was supplied and output_file(...) was never called, using default title 'Bokeh Plot'")
        title = "Bokeh Plot"

    if obj is None:
        if not curplot():
            warnings.warn("No current plot to save. Use renderer functions (circle, rect, etc.) to create a current plot (see http://bokeh.pydata.org/index.html)")
            return
        doc = curdoc()
    elif isinstance(obj, Widget):
        doc = Document()
        doc.add(obj)
    elif isinstance(obj, Document):
        doc = obj
    else:
        raise RuntimeError("Unable to save object of type '%s'" % type(obj))

    html = file_html(doc, resources, title)
    with io.open(filename, "w", encoding="utf-8") as f:
        f.write(decode_utf8(html))

def push(session=None, document=None):
    """ Updates the server with the data for the current document.

    Args:
        session (Sesion, optional) : filename to save document under (default: None)
            if `sessiokn` is None, the current output_server(...) session is used if present
        document (Document, optional) : BokehJS document to push
            if `document` is None, the current default document is pushed

    Returns:
        None

    """
    if not session:
        session = cursession()

    if not document:
        document = curdoc()

    if session:
        return session.store_document(curdoc())
    else:
        warnings.warn("push() called but no session was supplied and output_server(...) was never called, nothing pushed")

def _doc_wrap(func):
    extra_doc = "\nThis is a convenience function that acts on the current plot of the current document, and is equivalent to curlot().%s(...)\n\n" % func.__name__
    func.__doc__ = getattr(gf, func.__name__).__doc__ + extra_doc
    return deprecated(
        "Bokeh 0.7",
        "glyph methods on plots, e.g. plt.%s(...)" % func.__name__
    )(func)

def _plot_function(__func__, *args, **kwargs):
    retval = __func__(curdoc(), *args, **kwargs)
    if cursession() and curdoc().autostore:
        push()
    if _default_file and _default_file['autosave']:
        save()
    return retval

@_doc_wrap
def annular_wedge(x, y, inner_radius, outer_radius, start_angle, end_angle, **kwargs):
    return _plot_function(gf.annular_wedge, x, y, inner_radius, outer_radius, start_angle, end_angle, **kwargs)

@_doc_wrap
def annulus(x, y, inner_radius, outer_radius, **kwargs):
    return _plot_function(gf.annulus, x, y, inner_radius, outer_radius, **kwargs)

@_doc_wrap
def arc(x, y, radius, start_angle, end_angle, **kwargs):
    return _plot_function(gf.arc, x, y, radius, start_angle, end_angle, **kwargs)

@_doc_wrap
def asterisk(x, y, **kwargs):
    return _plot_function(gf.asterisk, x, y, **kwargs)

@_doc_wrap
def bezier(x0, y0, x1, y1, cx0, cy0, cx1, cy1, **kwargs):
    return _plot_function(gf.bezier, x0, y0, x1, y1, cx0, cy0, cx1, cy1, **kwargs)

@_doc_wrap
def circle(x, y, **kwargs):
    return _plot_function(gf.circle, x, y, **kwargs)

@_doc_wrap
def circle_cross(x, y, **kwargs):
    return _plot_function(gf.circle_cross, x, y, **kwargs)

@_doc_wrap
def circle_x(x, y, **kwargs):
    return _plot_function(gf.circle_x, x, y, **kwargs)

@_doc_wrap
def cross(x, y, **kwargs):
    return _plot_function(gf.cross, x, y, **kwargs)

@_doc_wrap
def diamond(x, y, **kwargs):
    return _plot_function(gf.diamond, x, y, **kwargs)

@_doc_wrap
def diamond_cross(x, y, **kwargs):
    return _plot_function(gf.diamond_cross, x, y, **kwargs)

@_doc_wrap
def image(image, x, y, dw, dh, **kwargs):
    return _plot_function(gf.image, image, x, y, dw, dh, **kwargs)

@_doc_wrap
def image_rgba(image, x, y, dw, dh, **kwargs):
    return _plot_function(gf.image_rgba, image, x, y, dw, dh, **kwargs)

@_doc_wrap
def image_url(url, x, y, **kwargs):
    return _plot_function(gf.image_url, url, x, y, **kwargs)

@_doc_wrap
def inverted_triangle(x, y, **kwargs):
    return _plot_function(gf.inverted_triangle, x, y, **kwargs)

@_doc_wrap
def line(x, y, **kwargs):
    return _plot_function(gf.line, x, y, **kwargs)

@_doc_wrap
def multi_line(xs, ys, **kwargs):
    return _plot_function(gf.multi_line, xs, ys, **kwargs)

@_doc_wrap
def oval(x, y, width, height, **kwargs):
    return _plot_function(gf.oval, x, y, width, height, **kwargs)

@_doc_wrap
def patch(x, y, **kwargs):
    return _plot_function(gf.patch, x, y, **kwargs)

@_doc_wrap
def patches(xs, ys, **kwargs):
    return _plot_function(gf.patches, xs, ys, **kwargs)

@_doc_wrap
def quad(left, right, top, bottom, **kwargs):
    return _plot_function(gf.quad, left, right, top, bottom, **kwargs)

@_doc_wrap
def quadratic(x0, y0, x1, y1, cx, cy, **kwargs):
    return _plot_function(gf.quadratic, x0, y0, x1, y1, cx, cy, **kwargs)

@_doc_wrap
def ray(x, y, length, angle, **kwargs):
    return _plot_function(gf.ray, x, y, length, angle, **kwargs)

@_doc_wrap
def rect(x, y, width, height, **kwargs):
    return _plot_function(gf.rect, x, y, width, height, **kwargs)

@_doc_wrap
def segment(x0, y0, x1, y1, **kwargs):
    return _plot_function(gf.segment, x0, y0, x1, y1, **kwargs)

@_doc_wrap
def square(x, y, **kwargs):
    return _plot_function(gf.square, x, y, **kwargs)

@_doc_wrap
def square_cross(x, y, **kwargs):
    return _plot_function(gf.square_cross, x, y, **kwargs)

@_doc_wrap
def square_x(x, y, **kwargs):
    return _plot_function(gf.square_x, x, y, **kwargs)

@_doc_wrap
def text(x, y, text, **kwargs):
    return _plot_function(gf.text, x, y, text, **kwargs)

@_doc_wrap
def triangle(x, y, **kwargs):
    return _plot_function(gf.triangle, x, y, **kwargs)

@_doc_wrap
def wedge(x, y, radius, start_angle, end_angle, **kwargs):
    return _plot_function(gf.wedge, x, y, radius, start_angle, end_angle, **kwargs)

@_doc_wrap
def x(x, y, **kwargs):
    return _plot_function(gf.x, x, y, **kwargs)

_marker_types = {
    "asterisk": asterisk,
    "circle": circle,
    "circle_cross": circle_cross,
    "circle_x": circle_x,
    "cross": cross,
    "diamond": diamond,
    "diamond_cross": diamond_cross,
    "inverted_triangle": inverted_triangle,
    "square": square,
    "square_x": square_x,
    "square_cross": square_cross,
    "triangle": triangle,
    "x": x,
    "*": asterisk,
    "+": cross,
    "o": circle,
    "ox": circle_x,
    "o+": circle_cross,
}

def markers():
    """ Prints a list of valid marker types for scatter()

    Returns:
        None
    """
    print(list(sorted(_marker_types.keys())))


_color_fields = set(["color", "fill_color", "line_color"])
_alpha_fields = set(["alpha", "fill_alpha", "line_alpha"])

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.scatter")
def scatter(*args, **kwargs):
    """ Creates a scatter plot of the given x and y items.

    Args:
        *args : The data to plot.  Can be of several forms:

            (X, Y)
                Two 1D arrays or iterables
            (XNAME, YNAME)
                Two bokeh DataSource/ColumnsRef

        marker (str, optional): a valid marker_type, defaults to "circle"
        color (color value, optional): shorthand to set both fill and line color

    All the :ref:`userguide_objects_line_properties` and :ref:`userguide_objects_fill_properties` are
    also accepted as keyword parameters.

    Examples:

        >>> scatter([1,2,3],[4,5,6], fill_color="red")
        >>> scatter("data1", "data2", source=data_source, ...)

    """
    ds = kwargs.get("source", None)
    names, datasource = _handle_1d_data_args(args, datasource=ds)
    kwargs["source"] = datasource

    markertype = kwargs.get("marker", "circle")

    # TODO: How to handle this? Just call curplot()?
    if not len(_color_fields.intersection(set(kwargs.keys()))):
        kwargs['color'] = get_default_color()
    if not len(_alpha_fields.intersection(set(kwargs.keys()))):
        kwargs['alpha'] = get_default_alpha()

    if markertype not in _marker_types:
        raise ValueError("Invalid marker type '%s'. Use markers() to see a list of valid marker types." % markertype)
    return _marker_types[markertype](*args, **kwargs)

def _deduplicate_plots(plot, subplots):
    doc = curdoc()
    doc.context.children = list(set(doc.context.children) - set(subplots))
    doc.add(plot)
    doc._current_plot = plot # TODO (bev) don't use private attrs

def _push_or_save():
    if cursession() and curdoc().autostore:
        push()
    if _default_file and _default_file['autosave']:
        save()

def gridplot(plot_arrangement, name=None, **kwargs):
    """ Generate a plot that arranges several subplots into a grid.

    Args:
        plot_arrangement (nested list of Plots) : plots to arrange in a grid
        name (str) : name for this plot
        **kwargs: additional attributes to pass in to GridPlot() constructor

    .. note:: `plot_arrangement` can be nested, e.g [[p1, p2], [p3, p4]]

    Returns:
        grid_plot: a new :class:`GridPlot <bokeh.models.plots.GridPlot>`
    """
    grid = GridPlot(children=plot_arrangement, **kwargs)
    if name:
        grid._id = name
    subplots = itertools.chain.from_iterable(plot_arrangement)
    _deduplicate_plots(grid, subplots)
    _push_or_save()
    return grid

# TODO (bev) remove after 0.7
def _axis(*sides):
    p = curplot()
    if p is None:
        return None
    objs = []
    for s in sides:
        objs.extend(getattr(p, s, []))
    axis = [obj for obj in objs if isinstance(obj, Axis)]
    return _list_attr_splat(axis)

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.xaxis")
def xaxis():
    """ Get the current `x` axis object(s)

    Returns:
        Returns x-axis object or splattable list of x-axis objects on the current plot
    """
    return _axis("above", "below")

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.yaxis")
def yaxis():
    """ Get the current `y` axis object(s)

    Returns:
        Returns y-axis object or splattable list of y-axis objects on the current plot
    """
    return _axis("left", "right")

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.axis")
def axis():
    """ Get all the current axis objects

    Returns:
        Returns axis object or splattable list of axis objects on the current plot
    """
    return _list_attr_splat(xaxis() + yaxis())

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.legend")
def legend():
    """ Get the current :class:`legend <bokeh.models.Legend>` object(s)

    Returns:
        Returns legend object or splattable list of legend objects on the current plot
    """
    p = curplot()
    if p is None:
        return None
    legends = [obj for obj in p.renderers if isinstance(obj, Legend)]
    return _list_attr_splat(legends)

# TODO (bev): remove after 0.7
def _grid(dimension):
    p = curplot()
    if p is None:
        return None
    grid = [obj for obj in p.renderers if isinstance(obj, Grid) and obj.dimension==dimension]
    return _list_attr_splat(grid)

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.xgrid")
def xgrid():
    """ Get the current `x` :class:`grid <bokeh.models.Grid>` object(s)

    Returns:
        Returns legend object or splattable list of legend objects on the current plot
    """
    return _grid(0)

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.ygrid")
def ygrid():
    """ Get the current `y` :class:`grid <bokeh.models.Grid>` object(s)

    Returns:
        Returns y-grid object or splattable list of y-grid objects on the current plot
    """
    return _grid(1)

@deprecated("Bokeh 0.7", "bokeh.plotting.Figure.grid")
def grid():
    """ Get the current :class:`grid <bokeh.models.Grid>` object(s)

    Returns:
        Returns grid object or splattable list of grid objects on the current plot
    """
    return _list_attr_splat(xgrid() + ygrid())

def load_object(obj):
    """updates object from the server
    """
    cursession().load_object(obj, curdoc())
