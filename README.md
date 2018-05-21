# How it works
pophttp is run as a service on a computer and acts like a fake LIFX light running on your LAN. You then configure the Logitech pop app to make this fake light different colors for each different switch and each unique color is translated into a standard HTTP request.

# Getting started
1. Install Python 2.6 or later, or Python 3.0 or later if you don't already have 1 of these versions installed.
2. Clone the repo and run `pophttp.py` with `-vv` from the local directory.
    ```bash
    git clone https://github.com/brokeh/pophttp
    cd pophttp
    ```
3. Copy the `config-sample.ini` file to `config.ini` to start making your changes
4. Start the script with some extra logging enabled to be able to see unconfigured lights
    ```bash
    python pophttp.py -vv
    ```
5. In the Logitech POP app on your phone, go to the _**My Devices**_ section and add _**LIFX**_. If you already have LIFX configured, tap refresh to find the new _**Pop HTTP**_ light.
6. Add the new _**Pop HTTP**_ light to any switch you want to use a HTTP request for, and choose a random color for it. It is recommended to use the _**Basic Mode**_ as this will make the switch more responsive to pressing it twice quickly.
7. Press the switch and check the console log for the pophttp server. You should see something like the following
    ```
    2017-04-23 22:05:07,742 192.168.1.25 request 31851h,36751s,32768b,3612k,on not mapped to a URL
    ```
    The `31851h,36751s,32768b,3612k,on` is the ID for the colour you chose, and what is going to be used to identify the light in the config file. Each component of the ID is optional and can be omitted if you want to match multiple actions. You will likely want to omit the final `,on` or `,off` so that it will match the same filter for both the on and off action.
8. Now add the new switch to the `config.ini` file under the `[switches]` section. You can include parameters from the fake light in the URL if required using `{}`. See the comments in the config file for full details on how to specify the URL.
    ```ini
    [switches]
    31851h,36751s,32768b,3612k = http://example.com/switch1?power={onoff}
    ```
    Notice that the `,on` is not included, but instead, the power state is included in the URL as `power={onoff}`.
9. Restart the python script for the config changes to take effect and you're done. Just repeat steps 6 - 8 for each switch.
10. Once you're done configuring everything, the `-vv` can be removed from the command to reduce the amount of output to the console.

# Advanced configuration
If you already have LIFX hardware it is recommended to also include the `ip_filter` option in the `config.ini` file to only respond to your pop bridge. You can find the IP of the bridge in the logs when running with `-vv`. This will prevent the fake light showing up in the LIFX app.

There are further configuration options available too. Check out the `config-sample.ini` provided to see a list of all configuration options and details on how to use them.