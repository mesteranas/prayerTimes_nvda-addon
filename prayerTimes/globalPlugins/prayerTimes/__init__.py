import datetime
import threading
import api
from . import handler
from gui import SettingsPanel, NVDASettingsDialog,guiHelper
import config
import wx
import gui
import globalPluginHandler
import ui
from scriptHandler import script
import addonHandler
import tones
addonHandler.initTranslation()
roleSECTION = "prayerTimes"
confspec = {
"auto_detect": "boolean(default=true)",
"lat": "string(default=0.0)",
"lon": "string(default=0.0)"}
config.conf.spec[roleSECTION] = confspec
cached_prayer_data = None
def getNextPrayer(prayer_str):
	lines = prayer_str.strip().split("\n")
	prayers = []
	for line in lines:
		if not line or _("Sunrise") in line:
			continue
		name, t_str = line.split(":", 1)
		p_time = datetime.datetime.strptime(t_str.strip(), "%I:%M %p").time()
		prayers.append((name.strip(), t_str.strip(), p_time))
	now_time = datetime.datetime.now().time()
	for name, t_str, p_time in prayers:
		if p_time > now_time:
			return f"{name}: {t_str}"
	if prayers:
		return f"{prayers[0][0]}: {prayers[0][1]}"
	return ""
class re(wx.Dialog):
	def __init__(self, text, title):
		super(re, self).__init__(gui.mainFrame, title=title)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.outputCtrl = wx.TextCtrl(self,style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH)
		self.outputCtrl .Bind(wx.EVT_KEY_DOWN, self.onOutputKeyDown)
		sizer.Add(self.outputCtrl, proportion=1, flag=wx.EXPAND)
		self.SetSizer(sizer)
		sizer.Fit(self)
		self.outputCtrl.SetValue(text)
		self.outputCtrl.SetFocus()
		self.Raise()
		self.Maximize()
		self.Show()
	def onOutputKeyDown(self, event):
		if event.GetKeyCode() == wx.WXK_ESCAPE:
			self.Close()
		event.Skip()
class CRSettingsPanel(SettingsPanel):
	title = _("prayer times")
	def makeSettings(self, settingsSizer):
		sHelper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self.auto_detect = sHelper.addItem(wx.CheckBox(self, label=_("Detect location automatically. Not accurate in all cases")))
		self.auto_detect.SetValue(config.conf[roleSECTION]["auto_detect"])
		self.auto_detect.Bind(wx.EVT_CHECKBOX, self.on_toggle_auto)
		self.lat_label = sHelper.addItem(wx.StaticText(self, label=_("Latitude")))
		self.lat_ctrl = sHelper.addItem(wx.TextCtrl(self))
		self.lat_ctrl.SetValue(config.conf[roleSECTION]["lat"])
		self.lat_ctrl.Bind(wx.EVT_CHAR, self.on_char)
		self.lon_label = sHelper.addItem(wx.StaticText(self, label=_("Longitude")))
		self.lon_ctrl = sHelper.addItem(wx.TextCtrl(self))
		self.lon_ctrl.SetValue(config.conf[roleSECTION]["lon"])
		self.lon_ctrl.Bind(wx.EVT_CHAR, self.on_char)
		self.on_toggle_auto(None)
	def on_char(self, event):
		k = event.GetUnicodeKey()
		if k >= 32 and chr(k).isalpha():
			return
		event.Skip()
	def on_toggle_auto(self, event):
		state = not self.auto_detect.GetValue()
		self.lat_label.Enable(state)
		self.lat_ctrl.Enable(state)
		self.lon_label.Enable(state)
		self.lon_ctrl.Enable(state)
	def postInit(self):
		self.auto_detect.SetFocus()
	def onSave(self):
		global cached_prayer_data
		cached_prayer_data = None
		config.conf[roleSECTION]["auto_detect"] = self.auto_detect.GetValue()
		lat_val = self.lat_ctrl.GetValue().strip()
		lon_val = self.lon_ctrl.GetValue().strip()
		config.conf[roleSECTION]["lat"] = lat_val if lat_val else "0.0"
		config.conf[roleSECTION]["lon"] = lon_val if lon_val else "0.0"
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	NVDASettingsDialog.categoryClasses.append(CRSettingsPanel)
	scriptCategory= _("prayer times")
	def fetch_data(self, callback):
		global cached_prayer_data
		if cached_prayer_data is not None:
			tones.beep(500, 100)
			wx.CallAfter(callback, cached_prayer_data)
			return
		try:
			if config.conf[roleSECTION]["auto_detect"]:
				lat, lon = handler.detectLocation()
			else:
				lat = float(config.conf[roleSECTION]["lat"])
				lon = float(config.conf[roleSECTION]["lon"])
			cached_prayer_data = handler.getCurrentPrayerTimes(lat, lon)
			prayer_data = cached_prayer_data 
		except Exception as e:
			prayer_data = _("error")
		tones.beep(500, 100)
		wx.CallAfter(callback, prayer_data )
	@script(gesture="kb:NVDA+alt+p")
	def script_toggle(self,gesture):
		ui.message(_("loading"))
		threading.Thread(target=self.fetch_data, args=(lambda res: re(res, _("Result")),)).start()
	script_toggle.__doc__= _("Get current prayer times")
	@script(gesture="kb:NVDA+shift+p")
	def script_toggle1(self,gesture):
		ui.message(_("loading"))
		threading.Thread(target=self.fetch_data, args=(lambda res: ui.message(getNextPrayer(res)),)).start()
	script_toggle1.__doc__= _("Get next prayer time")
	def terminate(self):
		NVDASettingsDialog.categoryClasses.remove(CRSettingsPanel)