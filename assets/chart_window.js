// "View Chart" opens the standalone /chart/<ticker> window. Lives here (an
// assets/*.js file, referenced via dash.ClientsideFunction) rather than as
// an inline JS string passed to clientside_callback() -- the inline-string
// form was intermittently failing with "Cannot read properties of
// undefined (reading 'apply')" in this app (a multi-page Dash app using
// use_pages=True), which points at dash-renderer not having the compiled
// function ready when the callback graph tries to invoke it. Files in
// assets/ are loaded as real <script> tags before dash-renderer starts, so
// window.dash_clientside.clientside.openChartWindow is guaranteed to exist
// by the time any callback tries to call it.
window.dash_clientside = Object.assign({}, window.dash_clientside, {
    clientside: {
        openChartWindow: function (
            n_clicks_list, ma_short, ma_long, bb_period, bb_stddev,
            stoch_mode, stoch_k_period, stoch_d_period, stoch_smoothing
        ) {
            const ctx = window.dash_clientside.callback_context;
            if (!ctx.triggered.length || !ctx.triggered[0].value || !ctx.triggered_id) {
                return window.dash_clientside.no_update;
            }
            const qs = new URLSearchParams({
                ma_short: ma_short, ma_long: ma_long,
                bb_period: bb_period, bb_stddev: bb_stddev, stoch_mode: stoch_mode,
                stoch_k_period: stoch_k_period, stoch_d_period: stoch_d_period, stoch_smoothing: stoch_smoothing,
                tf: "daily", chart_type: "candle",
            });
            window.open("/chart/" + encodeURIComponent(ctx.triggered_id.index) + "?" + qs.toString(), "_blank");
            return window.dash_clientside.no_update;
        },

        // Home page's ticker search bar: "select or write" -- a typed
        // ticker (free text, for anything not in the known-ticker
        // dropdown) wins over a dropdown pick if both are filled. Fires on
        // either the button click or pressing Enter in the text box, since
        // both should do the exact same thing. Uses whatever MA/BB/Stoch
        // defaults the page baked into a dcc.Store (config.py's values) --
        // this is a quick-look bar, not meant to duplicate every indicator
        // control from the other pages.
        openTickerSearchChart: function (n_clicks, n_submit, typedTicker, selectedTicker, defaults) {
            if (!n_clicks && !n_submit) {
                return window.dash_clientside.no_update;
            }
            const ticker = (typedTicker && typedTicker.trim()) ? typedTicker.trim().toUpperCase() : selectedTicker;
            if (!ticker) {
                return "Enter or select a ticker first.";
            }
            const qs = new URLSearchParams({
                ma_short: defaults.ma_short, ma_long: defaults.ma_long,
                bb_period: defaults.bb_period, bb_stddev: defaults.bb_stddev,
                stoch_mode: defaults.stoch_mode, stoch_k_period: defaults.stoch_k_period,
                stoch_d_period: defaults.stoch_d_period, stoch_smoothing: defaults.stoch_smoothing,
                tf: "daily", chart_type: "candle",
            });
            window.open("/chart/" + encodeURIComponent(ticker) + "?" + qs.toString(), "_blank");
            return "Opened chart for " + ticker + ".";
        }
    }
});
