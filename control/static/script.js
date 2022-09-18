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
    $(".alert[data-job-status]").each(function(i, flash) {
        const job_url = flash.dataset.jobStatus;
        const job_text = $(".job-text", flash).text();
        let retry = 2;
        function poll() {
            const req = $.ajax(job_url);
            req.done(function(job) {
                retry = 2;
                let delay = 2;
                if (job.state === "done") {
                    $(flash).removeClass("alert-primary").addClass("alert-success");
                    $(".message", flash).text("has completed.  Reload to see any changes.");
                    return;
                } else if (job.state === "failed") {
                    $(flash).removeClass("alert-primary").addClass("alert-danger");
                    $(".message", flash).text("has failed to complete.  The sysadmins have been notified.");
                    return;
                } else if (job.state === "withdrawn") {
                    $(flash).removeClass("alert-primary").addClass("alert-info");
                    $(".message", flash).text("has been withdrawn.  No changes have been made.");
                    return;
                } else if (job.state === "unapproved") {
                    $(flash).removeClass("alert-primary").addClass("alert-warning");
                    $(".message", flash).text("is awaiting approval from the sysadmins.");
                    delay = 30;
                } else if (job.state === "running") {
                    $(flash).removeClass("alert-warning").addClass("alert-primary");
                    $(".message", flash).text("is currently runnning, and will be completed shortly.");
                }
                setTimeout(poll, 1000 * delay);
            });
            req.fail(function() {
                setTimeout(poll, 1000 * retry);
                retry = Math.min(retry * 2, 30);
            });
        }
        poll();
    });
});
