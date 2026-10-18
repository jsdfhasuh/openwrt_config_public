'use strict';
'require baseclass';
'require fs';

var sensors = [
	{ label: 'CPU', path: '/sys/class/thermal/thermal_zone0/temp' },
	{ label: 'DDR', path: '/sys/class/thermal/thermal_zone1/temp' }
];

function formatTemperature(value) {
	if (typeof value !== 'string' || !/^-?\d+$/.test(value.trim()))
		return _('Not available');

	var temperature = Number(value.trim()) / 1000;
	if (!isFinite(temperature) || temperature < -55 || temperature > 150)
		return _('Not available');

	return temperature.toFixed(1) + ' \u00b0C';
}

return baseclass.extend({
	title: _('Temperature'),

	load: function() {
		return Promise.all(sensors.map(function(sensor) {
			return L.resolveDefault(fs.read(sensor.path), null);
		}));
	},

	render: function(data) {
		return E('table', { 'class': 'table' }, sensors.map(function(sensor, index) {
			return E('tr', { 'class': 'tr' }, [
				E('td', { 'class': 'td left', 'width': '33%' }, [sensor.label]),
				E('td', { 'class': 'td left' }, [formatTemperature(data && data[index])])
			]);
		}));
	}
});
