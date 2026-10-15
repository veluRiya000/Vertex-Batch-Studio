use super::Result;
use tauri::AppHandle;
use tauri_plugin_opener::OpenerExt;

#[derive(serde::Deserialize)]
#[serde(rename_all="snake_case")]
pub enum CloudPage {Project,Storage,Credentials}

fn destination(page:CloudPage,project:&str)->Result<String> {
    let path=match page {CloudPage::Project=>"welcome",CloudPage::Storage=>"storage/browser",CloudPage::Credentials=>"iam-admin/serviceaccounts"};
    let mut url=reqwest::Url::parse(&format!("https://console.cloud.google.com/{path}")).map_err(|e|e.to_string())?;
    let project=project.trim();
    if project.len()>128{return Err("项目 ID 过长".into());}
    if !project.is_empty(){url.query_pairs_mut().append_pair("project",project);}
    Ok(url.to_string())
}

/// Accept a fixed destination name, never an arbitrary URL from a webview.
#[tauri::command]
pub fn open_cloud_page(app:AppHandle,page:CloudPage,project:String)->Result<()> {
    app.opener().open_url(destination(page,&project)?,None::<String>).map_err(|e|e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn external_page_cannot_be_replaced_by_query_input() {
        let url=reqwest::Url::parse(&destination(CloudPage::Credentials,"demo-project&redirect=https://example.org").unwrap()).unwrap();
        assert_eq!(url.host_str(),Some("console.cloud.google.com"));
        assert_eq!(url.path(),"/iam-admin/serviceaccounts");
        assert_eq!(url.query_pairs().collect::<Vec<_>>(),vec![("project".into(),"demo-project&redirect=https://example.org".into())]);
    }
}
