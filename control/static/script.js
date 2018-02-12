$(document).ready(function() {
    $("#action-modal").on("shown.bs.modal", function(e) {
        $("#action-modal-content input[autofocus]").focus();
    });
    $("a[rel='modal']").click(function(ev) {
        $("#action-modal-content").empty()
        $.ajax({
            url: $(this).attr("href"),
            success: function(resp, status, jqXHR) {
                $("#action-modal-content").append($(resp).filter("main").contents());
                $("#action-modal").modal();
            },
            error: function(jqXHR, status, error) {
                $("#action-modal-content").html('Sorry, we\'re having trouble doing that.  Your Raven session may have expired &ndash; please reload the page and try again, or <a href="mailto:soc-srcf-admin@lists.cam.ac.uk">contact the sysadmins</a> if this message persists.');
                $("#action-modal").modal();
            }
        });
        ev.preventDefault();
    });
});
