$(document).ready(function() {
    $("a[rel='modal']").click(function(ev) {
        var $spinner = $("div.modal-spinner").show();
        $("#modal-content").remove();
        $.ajax({
            url: $(this).attr("href"),
            success: function(resp, status, jqXHR) {
                $spinner.hide();
                var $modal = $(resp).filter("div.main").attr("id", "modal-content");
                $modal.find("a.cancel").click(function(ev) {
                    $.modal.close();
                    ev.preventDefault();
                });
                $modal.appendTo("body").modal();
            },
            error: function(jqXHR, status, error) {
                $spinner.hide();
                $("<span>").attr("id", "modal-content").addClass("error")
                        .html("Oops, we're having trouble doing that.  If this message persists, please <a href=\"mailto:soc-srcf-admin@lists.cam.ac.uk\">contact the sysadmins</a>.")
                        .appendTo("body").modal();
            }
        });
        ev.preventDefault();
    });
});
