export namespace main {
	
	export class DecimatedScan {
	    id: number;
	    timestamp: string;
	    band: string;
	    hz_lo: number;
	    hz_hi: number;
	    step: number;
	    power: number[];
	
	    static createFrom(source: any = {}) {
	        return new DecimatedScan(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.timestamp = source["timestamp"];
	        this.band = source["band"];
	        this.hz_lo = source["hz_lo"];
	        this.hz_hi = source["hz_hi"];
	        this.step = source["step"];
	        this.power = source["power"];
	    }
	}
	export class ScanEvent {
	    band: string;
	    hz_lo: number;
	    hz_hi: number;
	    step: number;
	    power: number[];
	    timestamp: string;
	
	    static createFrom(source: any = {}) {
	        return new ScanEvent(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.band = source["band"];
	        this.hz_lo = source["hz_lo"];
	        this.hz_hi = source["hz_hi"];
	        this.step = source["step"];
	        this.power = source["power"];
	        this.timestamp = source["timestamp"];
	    }
	}
	export class ServerStatus {
	    mqtt_enabled: boolean;
	    mqtt_connected: boolean;
	    mqtt_status: string;
	    mqtt_broker: string;
	    web_enabled: boolean;
	    web_port: number;
	    web_running: boolean;
	
	    static createFrom(source: any = {}) {
	        return new ServerStatus(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.mqtt_enabled = source["mqtt_enabled"];
	        this.mqtt_connected = source["mqtt_connected"];
	        this.mqtt_status = source["mqtt_status"];
	        this.mqtt_broker = source["mqtt_broker"];
	        this.web_enabled = source["web_enabled"];
	        this.web_port = source["web_port"];
	        this.web_running = source["web_running"];
	    }
	}
	export class StatusEvent {
	    scanning: boolean;
	    current_band: string;
	    connected: boolean;
	
	    static createFrom(source: any = {}) {
	        return new StatusEvent(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.scanning = source["scanning"];
	        this.current_band = source["current_band"];
	        this.connected = source["connected"];
	    }
	}
	export class TimelineEntry {
	    id: number;
	    timestamp: string;
	    band: string;
	
	    static createFrom(source: any = {}) {
	        return new TimelineEntry(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.id = source["id"];
	        this.timestamp = source["timestamp"];
	        this.band = source["band"];
	    }
	}

}

export namespace models {
	
	export class BackendConfig {
	    type: string;
	    address: string;
	    port: number;
	    device: string;
	    url: string;
	    rbw: number;
	    vbw: number;
	    attenuation_db: number;
	
	    static createFrom(source: any = {}) {
	        return new BackendConfig(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.type = source["type"];
	        this.address = source["address"];
	        this.port = source["port"];
	        this.device = source["device"];
	        this.url = source["url"];
	        this.rbw = source["rbw"];
	        this.vbw = source["vbw"];
	        this.attenuation_db = source["attenuation_db"];
	    }
	}
	export class Band {
	    name: string;
	    start_hz: number;
	    stop_hz: number;
	    enabled: boolean;
	
	    static createFrom(source: any = {}) {
	        return new Band(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.name = source["name"];
	        this.start_hz = source["start_hz"];
	        this.stop_hz = source["stop_hz"];
	        this.enabled = source["enabled"];
	    }
	}
	export class CalibrationPoint {
	    frequency_mhz: number;
	    measured_dbm: number;
	
	    static createFrom(source: any = {}) {
	        return new CalibrationPoint(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.frequency_mhz = source["frequency_mhz"];
	        this.measured_dbm = source["measured_dbm"];
	    }
	}
	export class Calibration {
	    reference_dbm: number;
	    points: CalibrationPoint[];
	    // Go type: time
	    timestamp?: any;
	    rx_gain: number;
	
	    static createFrom(source: any = {}) {
	        return new Calibration(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.reference_dbm = source["reference_dbm"];
	        this.points = this.convertValues(source["points"], CalibrationPoint);
	        this.timestamp = this.convertValues(source["timestamp"], null);
	        this.rx_gain = source["rx_gain"];
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	
	export class WebConfig {
	    enabled: boolean;
	    port: number;
	    host: string;
	
	    static createFrom(source: any = {}) {
	        return new WebConfig(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.enabled = source["enabled"];
	        this.port = source["port"];
	        this.host = source["host"];
	    }
	}
	export class MQTTConfig {
	    enabled: boolean;
	    broker: string;
	    id: string;
	    token: string;
	    topic_prefix: string;

	    static createFrom(source: any = {}) {
	        return new MQTTConfig(source);
	    }

	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.enabled = source["enabled"];
	        this.broker = source["broker"];
	        this.id = source["id"];
	        this.token = source["token"];
	        this.topic_prefix = source["topic_prefix"];
	    }
	}
	export class Config {
	    device_id: string;
	    bands: Band[];
	    dwell_time_ms: number;
	    mode: string;
	    rx_gain: number;
	    rx_gain_mode: string;
	    auto_start: boolean;
	    backend?: BackendConfig;
	    mqtt?: MQTTConfig;
	    web?: WebConfig;
	    calibration?: Calibration;
	
	    static createFrom(source: any = {}) {
	        return new Config(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.device_id = source["device_id"];
	        this.bands = this.convertValues(source["bands"], Band);
	        this.dwell_time_ms = source["dwell_time_ms"];
	        this.mode = source["mode"];
	        this.rx_gain = source["rx_gain"];
	        this.rx_gain_mode = source["rx_gain_mode"];
	        this.auto_start = source["auto_start"];
	        this.backend = this.convertValues(source["backend"], BackendConfig);
	        this.mqtt = this.convertValues(source["mqtt"], MQTTConfig);
	        this.web = this.convertValues(source["web"], WebConfig);
	        this.calibration = this.convertValues(source["calibration"], Calibration);
	    }
	
		convertValues(a: any, classs: any, asMap: boolean = false): any {
		    if (!a) {
		        return a;
		    }
		    if (a.slice && a.map) {
		        return (a as any[]).map(elem => this.convertValues(elem, classs));
		    } else if ("object" === typeof a) {
		        if (asMap) {
		            for (const key of Object.keys(a)) {
		                a[key] = new classs(a[key]);
		            }
		            return a;
		        }
		        return new classs(a);
		    }
		    return a;
		}
	}
	

}

