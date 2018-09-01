# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2018, Galen Curwen-McAdams

import argparse
import atexit
import io
import textwrap
import redis
from PIL import Image as PImage
import attr
import colour
from lxml import etree

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image
from kivy.core.image import Image as CoreImage
from kivy.clock import Clock
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.dropdown import DropDown
from kivy.animation import Animation
from kivy.graphics import Color, Line, Ellipse, InstructionGroup
from kivy.graphics.vertex_instructions import Rectangle, Ellipse
from kivy.uix.label import Label
from kivy.properties import BooleanProperty

from ma_cli import data_models
from lings import ruling, pipeling
import fold_ui.keyling as keyling

r_ip, r_port = data_models.service_connection()
binary_r = redis.StrictRedis(host=r_ip, port=r_port)
redis_conn = redis.StrictRedis(host=r_ip, port=r_port, decode_responses=True)


@attr.s
class RegionPage(object):
    name = attr.ib()
    regions = attr.ib(default=attr.Factory(list))
    color = attr.ib(default=None)
    rules_widget = attr.ib(default=None)

    @property
    def scripts(self):
        scripts = "("
        for region in self.regions:
            # suffixes _key and _ocr
            scripts += textwrap.dedent('''$$(<"keli img-crop-to-key [*] $KEY --x1 {} --y1 {} --width {} --height {} --to-key {region}_key --db-port $DB_PORT --db-host $DB_HOST">),
                      $$(<"keli img-ocr-fan-in [*] {region}_key --to-key {region}_ocr --db-port $DB_PORT --db-host $DB_HOST">),'''.format(*region.coordinates_scaled, region=self.name))
        scripts += ")"
        return scripts

    @color.validator
    def check(self, attribute, value):
        if value is None:
            setattr(self,'color', colour.Color(pick_for=self))

    def as_xml(self):
        regionpage = etree.Element("regionpage")
        regionpage.set("color", self.color.hex_l)
        regionpage.set("name", self.name)
        for region in self.regions:
            regionpage.append(region.as_xml())
        for rule in self.rules_widget.as_xml():
            regionpage.append(rule)
        return regionpage

@attr.s
class Rule(object):
    source = attr.ib()
    symbol = attr.ib()
    values = attr.ib()
    destination = attr.ib()
    result = attr.ib()


@attr.s
class RuleWidget(object):
    source_widget = attr.ib()
    symbol_widget = attr.ib()
    values_widget = attr.ib()
    destination_widget = attr.ib()
    result_widget = attr.ib()
    enabled_widget = attr.ib()

    @property
    def enabled(self):
        if  self.enabled_widget.pressed:
            return True
        else:
            return False

    @property
    def rule(self):
        return Rule(source=self.source_widget.text,
                    symbol=self.symbol_widget.text,
                    values=self.values_widget.text,
                    destination=self.destination_widget.text,
                    result=self.result_widget.text)

@attr.s
class RuleSet(object):
    name = attr.ib(default="r")
    rules = attr.ib(default=attr.Factory(list))

    def script(self, keyling=False, newlines=True):
        scripts = "ruleset {} {{".format(self.name)
        if newlines:
            scripts += "\n"
        for rule in self.rules:
            if rule.enabled:
                # suffix _ocr
                scripts += '{source}_ocr {symbol} {values} -> {destination} {result}'.format(**attr.asdict(rule.rule))
                if newlines:
                    scripts += "\n"
        scripts += "}"

        if keyling is True:
            scripts = '''($$(<"keli src-ruling-str [*] --db-port $DB_PORT --db-host $DB_HOST  --ruling-string '{}'">),)'''.format(scripts)

        print(scripts)
        return scripts

@attr.s
class Region(object):
    name = attr.ib()
    color = attr.ib(default="")
    # x and y are upper left coordinates
    x = attr.ib(default=0)
    y = attr.ib(default=0)
    w = attr.ib(default=0)
    h = attr.ib(default=0)
    scaling_x = attr.ib(default=1)
    scaling_y = attr.ib(default=1)

    @property
    def y2(self):
        return self.y + self.h

    @property
    def x2(self):
        return self.x + self.w

    @property
    def coordinates_unscaled(self):
        return [self.x, self.y, self.w, self.h]

    @property
    def coordinates_scaled(self):
        return [int(self.x / self.scaling_x), int(self.y / self.scaling_y), int(self.w / self.scaling_x), int(self.h / self.scaling_y)]

    def as_xml(self):
        region = etree.Element("region")
        for k, v in attr.asdict(self).items():
            region.set(k, str(v))
        # store properties, not needed for recreating object
        coordinates_scaled = etree.Element("coordinates")
        coordinates_scaled.set("scaled", "True")
        coordinates_unscaled = etree.Element("coordinates")
        coordinates_unscaled.set("scaled", "False")
        for coords, coords_element in zip([self.coordinates_unscaled, self.coordinates_scaled], [coordinates_unscaled, coordinates_scaled]):
            for coord, coord_name in zip(coords, ["x", "y", "w", "h"]):
                coords_element.set(coord_name, str(coord))
        region.append(coordinates_unscaled)
        region.append(coordinates_scaled)
        return region

class DropDownInput(TextInput):
    def __init__(self, preload=None, preload_attr=None, preload_clean=True, **kwargs):
        self.multiline = False
        self.drop_down = DropDown()
        self.drop_down.bind(on_select=self.on_select)
        self.bind(on_text_validate=self.add_text)
        self.preload = preload
        self.preload_attr = preload_attr
        self.preload_clean = preload_clean
        self.not_preloaded = set()
        super(DropDownInput, self).__init__(**kwargs)
        self.add_widget(self.drop_down)

    def add_text(self,*args):
        if args[0].text not in [btn.text for btn in self.drop_down.children[0].children if hasattr(btn ,'text')]:
            btn = Button(text=args[0].text, size_hint_y=None, height=44)
            self.drop_down.add_widget(btn)
            btn.bind(on_release=lambda btn: self.drop_down.select(btn.text))
            if not 'preload' in args:
                self.not_preloaded.add(btn)

    def on_select(self, *args):
        self.text = args[1]
        if args[1] not in [btn.text for btn in self.drop_down.children[0].children if hasattr(btn ,'text')]:
            self.drop_down.append(Button(text=args[1]))
            self.not_preloaded.add(btn)
        # call on_text_validate after selection
        # to avoid having to select textinput and press enter
        self.dispatch('on_text_validate')

    def on_touch_down(self, touch):
        preloaded = set()
        if self.preload:
            for thing in self.preload:
                if self.preload_attr:
                    # use operator to allow dot access of attributes
                    thing_string = str(operator.attrgetter(self.preload_attr)(thing))
                else:
                    thing_string = str(thing)
                self.add_text(Button(text=thing_string),'preload')
                preloaded.add(thing_string)

        # preload_clean removes entries that
        # are not in the preload source anymore
        if self.preload_clean is True:
            added_through_widget = [btn.text for btn in self.not_preloaded if hasattr(btn ,'text')]
            for btn in self.drop_down.children[0].children:
                try:
                    if btn.text not in preloaded and btn.text not in added_through_widget:
                        self.drop_down.remove_widget(btn)
                except Exception as ex:
                    pass

        return super(DropDownInput, self).on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current == self:
            self.drop_down.open(self)
        return super(DropDownInput, self).on_touch_up(touch)

class EditViewViewer(BoxLayout):
    def __init__(self, view_source=None, config_hash=None, source_source=None, **kwargs):
        self.orientation = "vertical"
        # how to handle view_source update?
        # so that correct fields are displayed
        # different from a configuration update
        self.config_hash = config_hash
        self.view_source = view_source
        self.source_source = source_source
        self.buttons_container = BoxLayout(orientation="vertical", height=80, size_hint_y=None)
        self.write_fields_button = Button(text="write fields")
        self.write_fields_button.bind(on_press=self.write_fields)
        self.add_field_input = TextInput(hint_text="add field", multiline=False)
        self.add_field_input.bind(on_text_validate=lambda widget: self.create_field(widget.text, widget=widget))
        self.field_widgets = []
        self.delete_source_button = Button(text="remove entire")
        self.delete_source_button.bind(on_press=lambda widget: self.delete_source())

        super(EditViewViewer, self).__init__(**kwargs)
        # META_DB_KEY is the key used to write to database
        # it is added when source is retrieved and popped
        # before writing source
        self.fields_container = BoxLayout(orientation="vertical")
        if not "META_DB_KEY" in view_source:
            view_source.update({"META_DB_KEY" : str(uuid.uuid4())})
        if not "META_DB_TTL" in view_source:
            view_source.update({"META_DB_TTL" : str(-1)})
        self.update_field_rows()
        self.add_widget(self.fields_container)
        self.buttons_container.add_widget(self.write_fields_button)
        self.buttons_container.add_widget(self.add_field_input)
        self.buttons_container.add_widget(self.delete_source_button)

        self.add_widget(self.buttons_container)

    def delete_source(self):
        try:
            redis_conn.delete(self.view_source["META_DB_KEY"])
        except KeyError:
            pass

    def create_field(self, field, widget=None):
        if not field in self.view_source:
            self.view_source.update({field : ""})
            self.update_field_rows()
            if widget:
                widget.text = ""
                widget.hint_text = "add field"

    def remove_field(self, field, widget=None):
        try:
            self.view_source.pop(field)
            self.update_field_rows()
        except KeyError:
            pass

    def update_field_rows(self, source=None):
        self.fields_container.clear_widgets()
        self.field_widgets = []
        if source:
            self.view_source = source
        for field, value in self.view_source.items():
            row = BoxLayout()
            a = Label(text=str(field))
            row.add_widget(a)
            # dropdown?
            field_input = TextInput(text=str(value), multiline=False, height=a.height, font_size=a.font_size/1.5)
            field_input.field_for = str(field)
            field_input.bind(on_text_validate=lambda widget, field=field, value=value: self.update_field(field, widget.text, widget=widget))
            field_highlight_button = Button(text="$", size_hint_x=.1)
            field_highlight_button.bind(on_press=lambda widget, field=field: [self.source_source.set_env_var("$SELECTED_KEY", field), self.highlight_field()])
            field_remove_button = Button(text="X", size_hint_x=.1)
            field_remove_button.bind(on_press=lambda widget, field=field: self.remove_field(field))
            row.add_widget(field_input)
            row.highlight = field_highlight_button
            row.field = field
            row.add_widget(field_highlight_button)
            row.add_widget(field_remove_button)
            self.fields_container.add_widget(row)
            self.field_widgets.append(field_input)
        self.highlight_field()

    def highlight_field(self):
        for widget in self.fields_container.children:
            try:
                if widget.field == self.source_source.env_vars()["$SELECTED_KEY"]:
                    widget.highlight.background_color = [0, 1, 0, 1]
                else:
                    widget.highlight.background_color = [1, 1, 1, 1]
            except:
                pass

    def update_field(self, field, value, widget=None):
        if widget:
            current_background = widget.background_color
            anim = Animation(background_color=[0,1,0,1], duration=0.5) + Animation(background_color=current_background, duration=0.5)
            anim.start(widget)
        self.view_source[field] = value

    def write_fields(self, widget):
        # write contents if widget fields before button is
        # pressed in case user forgot to press enter after value
        #
        # for now, still require enter to be pressed for META_
        # prefixed fields since it may disrupt values such as ttl
        for w in self.field_widgets:
            if not "META_" in w.field_for:
                self.update_field(w.field_for, w.text, w)

        key_to_write = self.view_source.pop("META_DB_KEY")
        key_expiration = None
        try:
            key_expiration = self.view_source.pop("META_DB_TTL")
            key_expiration = int(key_expiration)
        except:
            pass

        # remove any 'META_' prefixed keys before writing to db
        for key in list(self.view_source.keys()):
            if key.startswith("META_"):
                self.view_source.pop(key)
        redis_conn.hmset(key_to_write, self.view_source)

        # if a field has been deleted in ui, delete it from hash
        for key in set(redis_conn.hgetall(key_to_write).keys()) -set(self.view_source.keys()):
            print("removing {}".format(key))
            redis_conn.hdel(key_to_write, key)

        if key_expiration and key_expiration > 0:
            redis_conn.expire(key_to_write, key_expiration)

class ClickableImage(Image):
    def __init__(self, **kwargs):
        self.key = None
        self.key_field = None
        self.selection_mode_selections = []
        super(ClickableImage, self).__init__(**kwargs)

    def reload(self):
        self.db_load(self.key, self.key_field)

    def db_load(self, key, key_field=None):
        self.key = key
        self.key_field = key_field
        if key_field is None:
            image_data = load_image(key)
        else:
            image_data = load_image(self.key_reference)

        try:
            self.texture = CoreImage(image_data, ext="jpg").texture
            self.size = self.norm_image_size
        except Exception as ex:
            print(ex)

    @property
    def key_reference(self):
        return redis_conn.hget(self.key, self.key_field)

    @property
    def key_value(self):
        k = redis_conn.hgetall(self.key)
        k.update({"META_DB_KEY" : self.key})
        return k

    # def on_touch_down(self, touch):
    #     if self.collide_point(*touch.pos):
    #         touch.grab(self)
    #         return True
    #     return super().on_touch_down(touch)

    def draw_regions(self):
        for region_page in self.app.region_pages:
            self.canvas.remove_group(region_page.name)
            for region in region_page.regions:
                r = self.img_to_canvas_coords(region.coordinates_unscaled)
                self.draw_region(r, [*region_page.color.rgb, 0.5], region_page.name)

    def draw_region(self, region, color=None, region_name=None):
        x, y, w, h = region
        if color is None:
            color = [128, 128, 128, 0.5]
        if region_name is None:
            region_name=""
        with self.canvas:
            Color(*color)
            Rectangle(pos=(x, y), size=(w, h), group=region_name)

    def img_to_canvas_coords(self, region):
        offset_x = int((self.size[0] - self.norm_image_size[0]) / 2)
        offset_y = 0
        if self.norm_image_size[0] > self.norm_image_size[1]:
            offset_y = int((self.size[1] - self.norm_image_size[1]) / 2) + self.norm_image_size[1]
        else:
            offset_y = self.norm_image_size[1]

        region[0] = region[0] + offset_x
        region[1] = abs(region[1] - offset_y) - region[3]
        return region

    def region_naming(self, x_pos, y_pos, img_width, img_height):
        name = ""
        col_width = img_width / 3
        row_width = img_height / 3

        if y_pos <= row_width:
            name += "top"
        elif row_width < y_pos <= row_width * 2:
             name += "middle"
        elif row_width * 2 < y_pos <= row_width * 3:
             name += "bottom"

        name += " "

        if x_pos <= col_width:
            name += "left"
        elif col_width < x_pos <= col_width * 2:
             name += "center"
        elif col_width * 2 < x_pos <= col_width * 3:
             name += "right"

        return name

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos):
            if touch.button == 'left':
                print("A clik1!!")
                offset_x = int((self.size[0] - self.norm_image_size[0]) / 2)
                offset_y = 0
                if self.norm_image_size[0] > self.norm_image_size[1]:
                    offset_y = int((self.size[1] - self.norm_image_size[1]) / 2) + self.norm_image_size[1]
                else:
                    offset_y = self.norm_image_size[1]

                tx = int(round(touch.x))
                ty = int(round(touch.y))
                adjusted_ty = int(ty - offset_y)
                adjusted_tx = int(tx - offset_x)
                if adjusted_ty <= 0:
                    adjusted_ty = abs(adjusted_ty)
                    if 0 < adjusted_ty < self.norm_image_size[1] and 0 < adjusted_tx < self.norm_image_size[0]:
                        # print("image coords x {} y {}".format(adjusted_tx, adjusted_ty))
                        self.selection_mode_selections.extend([adjusted_tx, adjusted_ty])
                        # draw a circle where click occured
                        with self.canvas:
                            Ellipse(pos=(tx, ty), size=(10, 10), group="region_clicks")

                        if len(self.selection_mode_selections) >= 4:
                            rect = self.selection_mode_selections[:4]
                            self.selection_mode_selections = []
                            self.canvas.remove_group("region_clicks")
                            x1 = 0
                            y1 = 0
                            if rect[0] > rect[2]:
                                w = rect[0] - rect[2]
                                x1 = rect[0] - w
                            else:
                                w = rect[2] - rect[0]
                                x1 = rect[2] - w

                            if rect[1] > rect[3]:
                                h = rect[1] - rect[3]
                                y1 = rect[1] - h
                            else:
                                h = rect[3] - rect[1]
                                y1 = rect[3] - h

                            region_name = self.region_naming(x1, y1, self.norm_image_size[0], self.norm_image_size[1])

                            # get scale
                            scale_x = self.norm_image_size[0] / self.texture_size[0]
                            scale_y = self.norm_image_size[1] / self.texture_size[1]

                            region = Region(name=region_name, x=x1, y=y1, w=w, h=h, scaling_x=scale_x, scaling_y=scale_y)
                            print("region from clicks", region)
                            try:
                                self.app.default_region_page.regions.append(region)
                                # a region has been added update xml
                                # and write session to db
                                self.app.session_to_db()
                                crop_rect = (int(x1 / scale_x) , int(y1 / scale_y), int(w / scale_x), int(h / scale_y))
                                self.selection_mode_selections = []
                                self.script.script_input.text = ""
                                if self.script.run_single_page_only:
                                    scripts = self.app.default_region_page.scripts
                                    rule_scripts =  self.app.default_region_page.rules_widget.ruleset.script(keyling=True, newlines=False)
                                else:
                                    scripts = ""
                                    rule_scripts = ""
                                    for r in self.app.region_pages:
                                        scripts += r.scripts + "\n"
                                        rule_scripts += r.rules_widget.ruleset.script(keyling=True, newlines=False)
                                if self.script.auto_run_scripts is True:
                                    self.script.run(scripts)
                                    self.script.run(rule_scripts)
                                self.script.script_input.text += scripts + "\n"
                                self.script.script_input.text += rule_scripts
                                self.draw_regions()
                                self.app.update_regions()
                            except Exception as ex:
                                print(ex)
                                anim = Animation(background_color=[1,0,0,1], duration=0.5) + Animation(background_color=[1,1,1,1], duration=0.5)
                                anim.start((self.app.region_page))

    def update_region_scripts(self):
        # used when a region is removed
        self.script.script_input.text = ""
        scripts = ""
        rule_scripts = ""
        if self.script.run_single_page_only:
            scripts = self.app.default_region_page.scripts
            rule_scripts =  self.app.default_region_page.rules_widget.ruleset.script(keyling=True, newlines=False)
        else:
            for r in self.app.region_pages:
                scripts += r.scripts + "\n"
                rule_scripts += r.rules_widget.ruleset.script(keyling=True, newlines=False)
        self.script.script_input.text += scripts + "\n"
        self.script.script_input.text += rule_scripts

class ToggleButton(Button):
    def __init__(self, **kwargs):
        self.pressed = False
        super(ToggleButton, self).__init__(**kwargs)

    def on_press(self):
        self.pressed = not self.pressed
        if self.pressed:
            self.background_color = [0, 1, 0, 1]

        else:
            self.background_color = [.9, .9, .9, 1]
        return super(ToggleButton, self).on_press()

    def draw_pressed_state(self):
        if self.pressed:
            self.background_color = [0, 1, 0, 1]
        else:
            self.background_color = [.9, .9, .9, 1]

class RuleWidgets(BoxLayout):
    def __init__(self, app=None, **kwargs):
        super(RuleWidgets, self).__init__(**kwargs)
        self.ruleset = RuleSet()
        self.app = app
        types_container = BoxLayout(orientation="vertical")
        for rule_type in ("int", "str", "roman", "Range", "STRING"):
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=30)
            rule_toggle = ToggleButton(text=rule_type, size_hint_x=None)
            row.add_widget(rule_toggle)
            setting_row = BoxLayout(orientation="horizontal")
            row.add_widget(setting_row)
            rule_toggle.bind(on_press=lambda widget, setting_row=setting_row: self.toggle_row(widget, setting_row))
            # store setting_row to allow updates from xml
            rule_toggle.setting_row = setting_row
            destination_widget = TextInput(multiline=False)
            result_widget = TextInput(multiline=False)
            # set widget values from region_page rules
            setting_row.add_widget(destination_widget)
            setting_row.add_widget(Label(text="becomes"))
            setting_row.add_widget(result_widget)
            r = RuleWidget(source_widget = self.app.region_page,
                           symbol_widget = Label(text="is"),
                           values_widget = rule_toggle,
                           destination_widget = destination_widget,
                           result_widget = result_widget,
                           enabled_widget = rule_toggle)
            self.ruleset.rules.append(r)
            types_container.add_widget(row)
            for child in setting_row.children:
                child.opacity = .2
        self.add_widget(types_container)

    def toggle_row(self, row_button, row, update_session=True):
        if row_button.pressed is False:
            for child in row.children:
                child.opacity = .2
        elif row_button.pressed is True:
            for child in row.children:
                child.opacity = 1
        # messy, since enabled state is used from the ToggleButton.pressed
        # the on_press call does not change it before calls to session_to_db
        # add a slight delay for now
        if update_session:
            Clock.schedule_once(lambda dt: self.app.session_to_db(), .1)


    def as_xml(self):
        rules = []
        for rule in self.ruleset.rules:
            rule_xml = etree.Element("rule")
            for k, v in attr.asdict(rule.rule).items():
                rule_xml.set(k, v)
            # enabled is a ToggleButton widget in RuleWidget
            # needed to recreate state
            rule_xml.set("enabled", str(rule.enabled_widget.pressed))
            rules.append(rule_xml)
        return rules

class RuleBox(BoxLayout):
    def __init__(self, app=None, **kwargs):
        self.types_container = BoxLayout(orientation="vertical")
        self.app = app
        super(RuleBox, self).__init__(**kwargs)
        self.add_widget(self.types_container)

    def load_rules(self, rules_widget):
        self.types_container.clear_widgets()
        self.types_container.add_widget(rules_widget)

class ScriptBox(BoxLayout):
    def __init__(self, source_widget, **kwargs):
        self.orientation = "vertical"
        self.script_input = TextInput(hint_text="()", multiline=True, size_hint_y=1)
        self.auto_run_scripts = True
        self.run_single_page_only = False
        self.sync_with_others = True
        self.run_script_this_button = Button(text="run script on this", size_hint_y=None, height=30)
        self.run_script_this_button.bind(on_press=lambda widget: self.run_script(self.script_input.text, widget=self.script_input))
        self.run_script_all_button = Button(text="run script on all ( {} )".format(self.all_sources_key), size_hint_y=None, height=30)
        self.run_script_all_button.bind(on_press=lambda widget: self.run_on_all())
        self.script_regenerate_button = Button(text="regenerate scripts", size_hint_y=None, height=30)
        self.script_regenerate_button.bind(on_press=lambda widget: self.source_widget.update_region_scripts())

        self.source_widget = source_widget
        super(ScriptBox, self).__init__(**kwargs)
        auto_run_checkbox = CheckBox(size_hint_x=None)
        if self.auto_run_scripts:
            auto_run_checkbox.active = BooleanProperty(True)
        auto_run_checkbox.bind(active=lambda widget, value, self=self: setattr(self, "auto_run_scripts", value))
        auto_run_row = BoxLayout(orientation="horizontal", height=30, size_hint_y=None)
        auto_run_row.add_widget(auto_run_checkbox)
        auto_run_row.add_widget(Label(text="auto run generated scripts", size_hint_x=None))
        run_single_page_only_checkbox = CheckBox(size_hint_x=None)
        if self.run_single_page_only:
            run_single_page_only_checkbox.active = BooleanProperty(True)
        run_single_page_only_checkbox.bind(active=lambda widget, value, self=self: setattr(self, "run_single_page_only", value))
        auto_run_row.add_widget(run_single_page_only_checkbox)
        auto_run_row.add_widget(Label(text="run this page region only", size_hint_x=None))
        sync_checkbox = CheckBox(size_hint_x=None)
        if self.sync_with_others:
            sync_checkbox.active = BooleanProperty(True)
        sync_checkbox.bind(active=lambda widget, value, self=self: [setattr(self, "sync_with_others", value), self.app.use_latest_session()])
        auto_run_row.add_widget(sync_checkbox)
        auto_run_row.add_widget(Label(text="sync with others", size_hint_x=None))

        self.add_widget(auto_run_row)
        self.add_widget(self.script_input)
        self.add_widget(self.run_script_this_button)
        self.add_widget(self.run_script_all_button)
        self.add_widget(self.script_regenerate_button)

    def run_on_all(self):
        sources = redis_conn.lrange(self.all_sources_key, 0, -1)
        for position, s in enumerate(sources):
            source = redis_conn.hgetall(s)
            source.update({"META_DB_KEY" : s})
            print("{} {}".format(position, s))
            self.run_script(self.script_input.text, widget=self.script_input, source=source)

    @property
    def all_sources_key(self):
        db_port = redis_conn.connection_pool.connection_kwargs["port"]
        db_host = redis_conn.connection_pool.connection_kwargs["host"]
        return "machinic:structured:{host}:{port}".format(host=db_host, port=db_port)

    def env_vars(self, source_uuid=None):
        db_port = redis_conn.connection_pool.connection_kwargs["port"]
        db_host = redis_conn.connection_pool.connection_kwargs["host"]
        env_vars = { "$DB_PORT" :  db_port,
                     "$DB_HOST" : db_host,
                     "$KEY" : self.source_widget.key_field
                   }
        # try to get position from fold-ui
        # may not be up-to-date
        if source_uuid is not None:
            try:
                source_position = redis_conn.lrange(self.all_sources_key, 0, -1).index(source_uuid)
                env_vars.update({"$SEQUENCE" : source_position})
            except:
                pass

        #env_vars.update(self.stored_env_vars)
        return env_vars

    def run_script(self, script, widget=None, source=None):
        if widget:
            current_background = widget.background_color
            model = None
            source_modified = None
            try:
                model = keyling.model(script)
                anim = Animation(background_color=[0,1,0,1], duration=0.5) + Animation(background_color=current_background, duration=0.5)
                anim.start(widget)
            except:
                anim = Animation(background_color=[1,0,0,1], duration=0.5) + Animation(background_color=current_background, duration=0.5)
                anim.start(widget)

            if model:
                if source is None:
                    source_modified = keyling.parse_lines(model, self.source_widget.key_value, self.source_widget.key_value["META_DB_KEY"], allow_shell_calls=True, env_vars=self.env_vars(self.source_widget.key_value["META_DB_KEY"]))
                else:
                    source_modified = keyling.parse_lines(model, source, source["META_DB_KEY"], allow_shell_calls=True, env_vars=self.env_vars(source["META_DB_KEY"]))
                # self.view_source = source_modified

            widget.background_color = [1, 1, 1, 1]

    def run(self, script):
        model = None
        try:
            model = keyling.model(script)
        except Exception as ex:
            print(ex)
            pass
        if model:
            source_modified = keyling.parse_lines(model, self.source_widget.key_value, self.source_widget.key_value["META_DB_KEY"], allow_shell_calls=True, env_vars=self.env_vars(self.source_widget.key_value["META_DB_KEY"]))

class DzzApp(App):

    def __init__(self, *args, **kwargs):
        # store kwargs to passthrough
        self.kwargs = kwargs
        self.region_pages = []
        self.default_region_page = None
        self.session_key_template = "dzz:session:{host}:{port}"
        if kwargs["db_host"] and kwargs["db_port"]:
            global binary_r
            global redis_conn
            db_settings = {"host" :  kwargs["db_host"], "port" : kwargs["db_port"]}
            binary_r = redis.StrictRedis(**db_settings)
            redis_conn = redis.StrictRedis(**db_settings, decode_responses=True)
        self.db_port = redis_conn.connection_pool.connection_kwargs["port"]
        self.db_host = redis_conn.connection_pool.connection_kwargs["host"]
        super(DzzApp, self).__init__()

    @property
    def session_key(self):
        return self.session_key_template.format(host=self.db_host, port=self.db_port)

    def save_session(self):
        pass

    def on_stop(self):
        # stop pubsub thread if window closed with '[x]'
        self.db_event_subscription.thread.stop()

    def app_exit(self):
        self.db_event_subscription.thread.stop()
        App.get_running_app().stop()

    def handle_db_events(self, message):
        msg = message["channel"].replace("__keyspace@0__:","")
        if msg in (self.img.key, self.img.key_reference):
            Clock.schedule_once(lambda dt: self.img.reload(), .1)

        if msg in (self.img.key):
            self.fields.update_field_rows(self.img.key_value)

        if msg in (self.session_key):
            Clock.schedule_once(lambda dt, msg=msg: self.update_session(etree.fromstring(redis_conn.hget(msg, "xml"))), .1)

    def update_session(self, xml):
        if self.img.script.sync_with_others:
            self.update_from_xml(xml)

    def update_from_xml(self, xml):
        print(etree.tostring(xml, pretty_print=True).decode())
        for session in xml.xpath('//session'):
            for regionpage_xml in session.xpath('//regionpage'):
                # create/update regionpages
                name = str(regionpage_xml.xpath("./@name")[0])
                color = str(regionpage_xml.xpath("./@color")[0])
                if not name in [region_page.name for region_page in self.region_pages]:
                    regionpage = RegionPage(name=name, color=colour.Color(color), rules_widget=RuleWidgets(app=self))
                    self.region_pages.append(regionpage)
                    if self.default_region_page is None:
                        self.default_region_page = regionpage
                        self.region_page.text = regionpage.name
                        # validate to enter in dropdown
                        self.region_page.dispatch('on_text_validate')
                        self.update_regions()
                        self.rule_box.load_rules(self.default_region_page.rules_widget)
                else:
                    regionpage = [region_page for region_page in self.region_pages if region_page.name == name][0]

                # create/update regions
                # use to delete existing regions
                created_regions = set()
                for region_xml in regionpage_xml.xpath('//region'):
                    r = {}
                    # use a copy of region attributes
                    r = dict(region_xml.attrib)

                    # try to convert back ints and floats
                    for k, v in r.items():
                        try:
                            r[k] = int(v)
                        except Exception as ex:
                            try:
                                r[k] = float(v)
                            except:
                                pass
                            pass

                    r = Region(**r)
                    print("region from xml: ",r)
                    created_regions.add(r.name)
                    if r.name in [region.name for region in regionpage.regions]:
                        to_remove = [region for region in regionpage.regions if region.name == r.name][0]
                        regionpage.regions.remove(to_remove)
                        regionpage.regions.append(r)
                    else:
                        regionpage.regions.append(r)

                for rule_xml in regionpage_xml.xpath('//rule'):
                    # create/update rules
                    rule = dict(rule_xml.attrib)
                    for r in regionpage.rules_widget.ruleset.rules:
                        # rule widgets already exist, they are created
                        # by parent widget, match using values and then
                        # update
                        if r.values_widget.text == rule["values"]:
                            r.destination_widget.text = rule["destination"]
                            r.result_widget.text = rule["result"]
                            if rule["enabled"].lower() == "true":
                                enabled_state = True
                            else:
                                enabled_state = False
                            r.enabled_widget.pressed = enabled_state
                            # update to toggle enabled correctly...
                            r.enabled_widget.draw_pressed_state()
                            # set toggle_row state too
                            regionpage.rules_widget.toggle_row(r.enabled_widget, r.enabled_widget.setting_row, update_session=False)

                # remove regions if needed
                existing_regions = set([region.name for region in regionpage.regions])
                remove_regions = existing_regions - created_regions
                print("removing ", remove_regions, existing_regions, created_regions)
                for region in list(regionpage.regions):
                    if region.name in remove_regions:
                        regionpage.regions.remove(region)

        self.update_regions()
        # call draw_regions with a slight delay to
        # make sure canvas is loaded, otherwise rectangles
        # are drawn with incorrect coordinates
        Clock.schedule_once(lambda dt, : self.img.draw_regions(), 0.5)

    def set_region_page(self, widget):
        if not widget.text in [region_page.name for region_page in self.region_pages]:
            region = RegionPage(name=widget.text, rules_widget=RuleWidgets(app=self))
            self.region_pages.append(region)
            self.default_region_page = region
        else:
            for region in self.region_pages:
                if region.name == widget.text:
                    self.default_region_page = region
        self.update_regions()
        self.rule_box.load_rules(self.default_region_page.rules_widget)

    def update_regions(self):
        self.region_container.clear_widgets()
        for region in self.default_region_page.regions:
            row = BoxLayout(orientation="horizontal", height=30, size_hint_y=None)
            row.add_widget(Button(background_color=(*self.default_region_page.color.rgb,1), text=" "))
            change_region_name = TextInput(text=region.name, multiline=False)
            change_region_name.bind(on_text_validate=lambda widget, region=region: setattr(region, "name", widget.text))
            row.add_widget(change_region_name)
            remove_region = Button(text="remove")
            remove_region.bind(on_press=lambda widget, region=region, region_page=self.default_region_page: [region_page.regions.remove(region), self.update_regions(), self.img.draw_regions(), self.img.update_region_scripts(), self.session_to_db()])
            row.add_widget(remove_region)
            self.region_container.add_widget(row)

    def as_xml(self):
        session = etree.Element("session")
        for rp in self.region_pages:
            session.append(rp.as_xml())
        return session

    def session_to_db(self):
        session_string = etree.tostring(self.as_xml(), pretty_print=True).decode()
        if self.img.script.sync_with_others:
            redis_conn.hmset(self.session_key, {"xml" : session_string})

    def use_latest_session(self):
        try:
            self.update_session(etree.fromstring(redis_conn.hget(self.session_key, "xml")))
        except Exception as ex:
            print(ex)

    def build(self):
        root = BoxLayout()
        self.img = ClickableImage()
        self.img.app = self
        root.add_widget(self.img)
        self.img.db_load(self.kwargs["db_key"], self.kwargs["db_key_field"])
        script_box = ScriptBox(source_widget=self.img, size_hint_y=.5)
        #set app for access to rule_box
        script_box.app = self
        region_page = DropDownInput(hint_text="enter a regionpage name", height=60, size_hint_y=None, font_size="30sp")
        region_page.bind(on_text_validate=lambda widget: self.set_region_page(widget))
        self.region_page = region_page
        self.region_container = BoxLayout(orientation="vertical", size_hint_y=None)
        tool_container = BoxLayout(orientation="vertical")
        upper_container = BoxLayout(orientation="horizontal", size_hint_y=.5)
        upper_left_container = BoxLayout(orientation="vertical")
        upper_right_container = BoxLayout(orientation="vertical")

        self.img.script = script_box
        tool_container.add_widget(region_page)
        self.rule_box = RuleBox(app=self)
        upper_right_container.add_widget(self.rule_box)
        upper_left_container.add_widget(self.region_container)
        #upper_left_container.add_widget(script_box)
        upper_container.add_widget(upper_left_container)
        upper_container.add_widget(upper_right_container)
        tool_container.add_widget(upper_container)
        self.fields = EditViewViewer(self.img.key_value)
        tool_container.add_widget(script_box)
        tool_container.add_widget(self.fields)
        root.add_widget(tool_container)

        self.db_event_subscription = redis_conn.pubsub()
        self.db_event_subscription.psubscribe(**{'__keyspace@0__:*': self.handle_db_events})
        # add thread to pubsub object to stop() on exit
        self.db_event_subscription.thread = self.db_event_subscription.run_in_thread(sleep_time=0.001)
        # try to get existing/latest session
        self.use_latest_session()
        return root

def load_image(uuid, new_size=None):
    contents = binary_r.get(uuid)
    f = io.BytesIO()
    f = io.BytesIO(contents)
    if new_size:
        img = PImage.open(f)
        img.thumbnail((new_size, new_size), PImage.ANTIALIAS)
        extension = img.format
        file = io.BytesIO()
        img.save(file, extension)
        img.close()
        file.seek(0)
    else:
        file = f
    return file

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-key",  help="db hash key")
    parser.add_argument("--db-key-field",  help="db hash field")

    parser.add_argument("--db-host",  help="db host ip, requires use of --db-port")
    parser.add_argument("--db-port", type=int, help="db port, requires use of --db-host")
    args = parser.parse_args()

    if bool(args.db_host) != bool(args.db_port):
        parser.error("--db-host and --db-port values are both required")

    app = DzzApp(**vars(args))
    atexit.register(app.save_session)
    app.run()