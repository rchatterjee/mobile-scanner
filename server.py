from flask import (
    Flask, render_template, request, redirect, g, jsonify,
    url_for
)
import logging
from logging.handlers import RotatingFileHandler
from phone_scanner import AndroidScan, IosScan, TestScan
import json
import blacklist
import config
from time import strftime
import traceback
from privacy_scan_android import do_privacy_check
from db import (
    get_db, create_scan, save_note, create_appinfo, update_appinfo,
    create_report, new_client_id, init_db, create_mult_appinfo,
    get_client_devices_from_db, get_device_from_db, update_mul_appinfo, get_serial_from_db
)


app = Flask(__name__, static_folder='webstatic')
# app.config['STATIC_FOLDER'] = 'webstatic'
android = AndroidScan()
ios = IosScan()
test = TestScan()


def get_device(k):
    return {
        'android': android,
        'ios': ios,
        'test': test
    }.get(k)



@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.route("/", methods=['GET'])
def index():
    return render_template(
        'main.html',
        title=config.TITLE,
        device_primary_user=config.DEVICE_PRIMARY_USER,
        task = 'home',
        devices={
            'Android': android.devices(),
            'iOS': ios.devices(),
            'Test': test.devices()
        },
        apps={},
        clientid=new_client_id()
    )


@app.route('/details/app/<device>', methods=['GET'])
def app_details(device):
    sc = get_device(device)
    appid = request.args.get('appId')
    ser = request.args.get('serial')
    d, info = sc.app_details(ser, appid)
    d = d.to_dict(orient='index').get(0, {})
    d['appId'] = appid

    ## detect apple and put the key into d.permissions
    #if "Ios" in str(type(sc)):
    #    print("apple iphone")
    #else:
    #    print(type(sc))
    
    print(d.keys())
    return render_template(
        'main.html', task="app",
        title=config.TITLE,
        device_primary_user=config.DEVICE_PRIMARY_USER,
        app=d,
        info=info,
        device=device
    )


@app.route('/instruction', methods=['GET'])
def instruction():
    return render_template('main.html', task="instruction",
        device_primary_user=config.DEVICE_PRIMARY_USER,
        title=config.TITLE)


@app.route('/kill', methods=['POST', 'GET'])
def killme():
    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        raise RuntimeError('Not running with the Werkzeug Server')
    func()
    return ("The app has been closed!")


def is_success(b, msg_succ="", msg_err=""):
    if b:
        return msg_succ if msg_succ else "Success!", 200
    else:
        return msg_err if msg_err else "Failed", 401

def first_element_or_none(l):
    if l and len(l)>0:
        return l[0]

@app.route("/privacy", methods=['GET'])
def privacy():
    """
    TODO: Privacy scan. Think how should it flow. 
    Privacy is a seperate page. 
    """
    return render_template('main.html', task="privacy", 
            device_primary_user=config.DEVICE_PRIMARY_USER,
            title=config.TITLE)

@app.route("/privacy/<device>/<cmd>", methods=['GET'])
def privacy_scan(device, cmd):
    sc = get_device(device)
    res = do_privacy_check(sc.serialno, cmd)
    return res

@app.route("/view_results", methods=['POST', 'GET'])
def view_results():
    clientid = request.form.get('clientid', request.args.get('clientid'))
    scan_res = request.form.get('scan_res', request.args.get('scan_res'))

    # TODO: maybe unneccessary, but likely nice for returning without re-drawing screen.
    last_serial = request.form.get('last_serial', request.args.get('last_serial'))

    if scan_res == last_serial:
        print('Should return same template as before.')
        print("scan_res:"+str(scan_res))
        print("last_serial:"+str(last_serial))
    else:
        print('Should return results of scan_res.')
        print("scan_res:"+str(scan_res))
        print("last_serial:"+str(last_serial))

@app.route("/scan", methods=['POST', 'GET'])
def scan():
    """
    Needs three attribute for a device
    :param device: "android" or "ios" or test
    :return: a flask view template
    """
    # FIXME: prevent clientID modification (remove it from GET params?)
    clientid = request.form.get('clientid', request.args.get('clientid'))
    device_primary_user = request.form.get('device_primary_user', \
            request.args.get('device_primary_user'))
    device = request.form.get('device', request.args.get('device'))
    action = request.form.get('action', request.args.get('action'))

    currently_scanned = get_client_devices_from_db(clientid)
    # lookup devices scanned so far here. need to add this by model rather than by serial.
    print('CURRENTLY SCANNED: {}'.format(currently_scanned))
    print('PRIMARY USER IS: {}'.format(device_primary_user))
    print('-'*80)
    print('CLIENT ID IS: {}'.format(clientid))
    print('-'*80)
    print("--> Action = ", action)
    # if action == "Privacy Check":
    #     return redirect(url_for(privacy, device=device), code=302)
    sc = get_device(device)
    if not sc:
        return render_template("main.html",
                               task="home",
                               title=config.TITLE,
                               device_primary_user=config.DEVICE_PRIMARY_USER,
                               apps={},
                               currently_scanned=currently_scanned,
                               error="Please choose one device to scan.",
                               device_primary_user_sel=device_primary_user,
                               clientid=clientid
        )
    if not device_primary_user:
        return render_template("main.html",
                               task="home",
                               title=config.TITLE,
                               device_primary_user=config.DEVICE_PRIMARY_USER,
                               apps={},
                               device=device,
                               currently_scanned=currently_scanned,
                               error="Please identify the primary user of the device.",
                               clientid=clientid
        )
    ser = sc.devices()

    if isinstance(ser, str):
        # FIXME: add pkexec scripts/ios_mount_linux.sh workflow for iOS if needed.
        return render_template(
            "main.html", task="home", apps={},
            title=config.TITLE,
            device_primary_user=config.DEVICE_PRIMARY_USER,
            device_primary_user_sel=device_primary_user,
            clientid=clientid,
            device=device,
            currently_scanned=currently_scanned,
            error="<b>Android device detected, but needs to be set to File Transer Mode. Please follow the <a href='/instruction' target='_blank' rel='noopener'>setup instructions here.</a></b> {}".format(error)
    )

    ser = first_element_or_none(ser)
    # clientid = new_client_id()
    print(">>>scanning_device", device, ser, "<<<<<")
    error = "If an iPhone is connected, open iTunes, click through the connection dialog and wait for the \"Trust this computer\" prompt "\
    "to pop up in the iPhone, and then scan again." if device == 'ios' else\
    "If an Android device is connected, disconnect and reconnect the device, make sure "\
    "developer options is activated and USB debugging is turned on on the device, and then scan again."

    if device == 'ios':
        isconnected, reason = sc.setup() # go through pairing process and do not scan until it is successful.
        if not isconnected:
            return render_template(
                "main.html", task="home", 
                apps={},
                title=config.TITLE,
                device_primary_user=config.DEVICE_PRIMARY_USER,
                device_primary_user_sel=device_primary_user,
                clientid=clientid,
                device=device,
                currently_scanned=currently_scanned,
                error="<b>{}</b>".format(reason+"<b>Please follow the <a href='/instruction' target='_blank' rel='noopener'>setup instructions here,</a> if needed.</b>"))
    if not ser:
        # FIXME: add pkexec scripts/ios_mount_linux.sh workflow for iOS if needed.
        return render_template(
            "main.html", task="home", apps={},
            title=config.TITLE,
            device_primary_user=config.DEVICE_PRIMARY_USER,
            device_primary_user_sel=device_primary_user,
            clientid=clientid,
            device=device,
            currently_scanned=currently_scanned,
            error="<b>No device is connected. Please follow the <a href='/instruction' target='_blank' rel='noopener'>setup instructions here.</a></b> {}".format(error)
    )

    # TODO: model for 'devices scanned so far:' device_name_map['model']
    # and save it to scan_res along with device_primary_user.
    device_name_print, device_name_map = sc.device_info(serial=ser)

    # @apps have appid, title, flags, TODO: add icon
    apps = sc.find_spyapps(serialno=ser).fillna('').to_dict(orient='index')

    scan_d = {'clientid':clientid, 'serial':ser, 'device':device,
            'device_model':device_name_map['model'].strip(),
            'device_version':device_name_map['version'].strip(),
            'device_primary_user':device_primary_user,
    }

    if device == 'ios':
        scan_d['device_manufacturer'] = 'Apple'
        scan_d['last_full_charge'] = 'unknown'
    else:
        scan_d['device_manufacturer'] = device_name_map['brand'].strip()
        scan_d['last_full_charge'] = device_name_map['last_full_charge']

    rooted, rooted_reason = sc.isrooted(ser)
    scan_d['is_rooted'] = rooted
    scan_d['rooted_reasons'] = json.dumps(rooted_reason)

    # TODO: here, adjust client session.
    scanid = create_scan(scan_d)

    print("Creating appinfo...")
    create_mult_appinfo([(scanid, appid, json.dumps(info['flags']), '', '<new>')
                          for appid, info in apps.items()])

    currently_scanned = get_client_devices_from_db(clientid)
    return render_template(
        'main.html', task="home",
        isrooted = "Yes. Reason(s): {}".format(rooted_reason) if rooted else "Don't know" if rooted is None \
                else "No. Reason(s): {}".format(rooted_reason),
        title=config.TITLE,
        device_primary_user=config.DEVICE_PRIMARY_USER,
        device_primary_user_sel=device_primary_user,
        device_name=device_name_print,
        apps=apps,
        scanid=scanid,
        clientid=clientid,
        sysapps=set(), #sc.get_system_apps(serialno=ser)),
        serial=ser,
        device=device,
        currently_scanned=currently_scanned, # TODO: make this a map of model:link to display scan results for that scan.
        error=config.error(),
    )


##############  RECORD DATA PART  ###############################


@app.route("/delete/app/<scanid>", methods=["POST", "GET"])
def delete_app(scanid):
    device = get_device_from_db(scanid)
    serial = get_serial_from_db(scanid)
    sc = get_device(device)
    appid = request.form.get('appid')
    remark = request.form.get('remark')
    action = "delete"
    # TODO: Record the uninstall and note
    r = sc.uninstall(serial=serial, appid=appid)
    if r:
        r = update_appinfo(
            scanid=scanid, appid=appid, remark=remark, action=action
        )
        print("Update appinfo failed! r={}".format(r))
    else:
        print("Uninstall failed. r={}".format(r))
    return is_success(r, "Success!", config.error())


# @app.route('/save/appnote/<device>', methods=["POST"])
# def save_app_note(device):
#     sc = get_device(device)
#     serial = request.form.get('serial')
#     appId = request.form.get('appId')
#     note = request.form.get('note')
#     return is_success(sc.save('appinfo', serial=serial, appId=appId, note=note))

@app.route('/saveapps/<scanid>', methods=["POST"])
def record_applist(scanid):
    device = get_device_from_db(scanid)
    sc = get_device(device)
    d = request.form
    update_mul_appinfo([(remark, scanid, appid)
                        for appid, remark in d.items()])
    return "Success", 200


@app.route('/savescan/<scanid>', methods=["POST"])
def record_scanres(scanid):
    device = get_device_from_db(scanid)
    sc = get_device(device)
    note = request.form.get('notes')
    r = save_note(scanid, note)
    create_report(request.form.get('clientid'))
    return is_success(r, "Success!", "Could not save the form. See logs in the terminal.")




################# For logging ##############################################
@app.route("/error")
def get_nothing():
    """ Route for intentional error. """
    return "foobar" # intentional non-existent variable


@app.after_request
def after_request(response):
    """ Logging after every request. """
    # This avoids the duplication of registry in the log,
    # since that 500 is already logged via @app.errorhandler.
    if response.status_code != 500:
        ts = strftime('[%Y-%b-%d %H:%M]')
        logger.error('%s %s %s %s %s %s',
                      ts,
                      request.remote_addr,
                      request.method,
                      request.scheme,
                      request.full_path,
                      response.status)
    return response


# @app.errorhandler(Exception)
# def exceptions(e):
#     """ Logging after every Exception. """
#     ts = strftime('[%Y-%b-%d %H:%M]')
#     tb = traceback.format_exc()
#     logger.error('%s %s %s %s %s 5xx INTERNAL SERVER ERROR\n%s',
#                   ts,
#                   request.remote_addr,
#                   request.method,
#                   request.scheme,
#                   request.full_path,
#                   tb)
#     print(e, file=sys.stderr)
#     return "Internal server error", 500





if __name__ == "__main__":
    from imp import reload
    import sys
    if 'TEST' in sys.argv[1:] or 'test' in sys.argv[1:]:
        print("Running in test mode.")
        config.set_test_mode(True)
        print("Checking mode = {}\nApp flags: {}\nSQL_DB: {}"
              .format(config.TEST, config.APP_FLAGS_FILE,
                      config.SQL_DB_PATH))


    init_db(app, force=(not config.TEST))
    handler = RotatingFileHandler('logs/app.log', maxBytes=100000,
                                  backupCount=30)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.ERROR)
    logger.addHandler(handler)

    app.run(host="0.0.0.0", port=5000, debug=config.DEBUG)

