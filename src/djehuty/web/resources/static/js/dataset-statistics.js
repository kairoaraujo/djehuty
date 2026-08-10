// Period selector for the dataset usage-statistics panel. Re-fetches the
// view/download counts for the selected period and updates the numbers in place.
// Only views and downloads are period-aware; other metrics (shares, cites) are
// left untouched because they are not recorded in the SQL usage-statistics store.

function update_dataset_statistics (container_uuid, period) {
    let parameters = {};
    if (period !== "") { parameters["period"] = period; }

    jQuery.get("/v3/datasets/" + container_uuid + "/statistics", parameters)
        .done(function (data) {
            ["views", "downloads"].forEach(function (metric) {
                let cell = jQuery('#usage .number[data-metric="' + metric + '"]');
                if (cell.length && data[metric] !== undefined) {
                    cell.text(data[metric]);
                }
            });
        });
}

jQuery(document).ready(function () {
    let usage = jQuery("#usage");
    let container_uuid = usage.data("container-uuid");
    if (!container_uuid) { return; }

    function select_period (period) {
        jQuery("#usage-period .active").removeClass("active");
        jQuery(".period-" + (period === "" ? "all" : period)).addClass("active");
        update_dataset_statistics(container_uuid, period);
    }

    jQuery("li.period-all a").on("click", function () { select_period(""); return false; });
    jQuery("li.period-last_month a").on("click", function () { select_period("last_month"); return false; });
    jQuery("li.period-last_week a").on("click", function () { select_period("last_week"); return false; });
});
