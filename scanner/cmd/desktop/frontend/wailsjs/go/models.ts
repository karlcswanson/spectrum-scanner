export namespace main {
	
	export class ServerStatus {
	    mqtt_enabled: boolean;
	    mqtt_connected: boolean;
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
	    name: string;
	    location: string;
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
	        this.name = source["name"];
	        this.location = source["location"];
	        this.topic_prefix = source["topic_prefix"];
	    }
	}
	export class Config {
	    device_id: string;
	    name: string;
	    description: string;
	    bands: Band[];
	    dwell_time_ms: number;
	    mode: string;
	    rx_gain: number;
	    rx_gain_mode: string;
	    auto_start: boolean;
	    backend?: BackendConfig;
	    mqtt?: MQTTConfig;
	    web?: WebConfig;
	
	    static createFrom(source: any = {}) {
	        return new Config(source);
	    }
	
	    constructor(source: any = {}) {
	        if ('string' === typeof source) source = JSON.parse(source);
	        this.device_id = source["device_id"];
	        this.name = source["name"];
	        this.description = source["description"];
	        this.bands = this.convertValues(source["bands"], Band);
	        this.dwell_time_ms = source["dwell_time_ms"];
	        this.mode = source["mode"];
	        this.rx_gain = source["rx_gain"];
	        this.rx_gain_mode = source["rx_gain_mode"];
	        this.auto_start = source["auto_start"];
	        this.backend = this.convertValues(source["backend"], BackendConfig);
	        this.mqtt = this.convertValues(source["mqtt"], MQTTConfig);
	        this.web = this.convertValues(source["web"], WebConfig);
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

