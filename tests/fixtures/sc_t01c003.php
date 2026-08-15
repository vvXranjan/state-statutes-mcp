
	<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
	
	<html xmlns="http://www.w3.org/1999/xhtml" lang="en">
	<head>
		<meta http-equiv="X-UA-Compatible" content="IE=edge" />
	    <meta name="robots" content="noimageindex">
	    <meta charset="iso-8859-1">
	    <META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=ISO-8859-1">
	    	    <title>Code of Laws - Title 1 - Chapter 3- - ADMINISTRATION OF THE GOVERNMENT</title>
	    <link rel="SHORTCUT ICON" href="/images/stateflagsmall.ico" />
		<link rel="icon" href="/images/stateflagsmall.ico" type="image/ico" />
		<link rel="SHORTCUT ICON" href="/images/South-Carolina-Flag2.ico" />

		<link type="text/css" rel="stylesheet" href="/css/main.css" media="all" />
				
		<!--[if lte IE 7]>
		<link type="text/css" rel="stylesheet" href="/css/ie7main.css" media="all" />
		<![endif]-->
		<!--[if gte IE 7]>
		<link type="text/css" rel="stylesheet" href="/css/iemain.css" media="all" />
		<![endif]-->
		<link type="text/css" rel="stylesheet" href="/css/print.css" media="print" />
		<link type="text/css" rel="stylesheet" href="/css/supplement.css" media="screen" />
		<!--<link type="text/css" rel="stylesheet" href="/css/zipsearch.css" media="screen" />
		<link type="text/css" rel="stylesheet" href="/css/vote.css" media="screen" />
		<link type="text/css" rel="stylesheet" href="/css/contact.css" media="screen" />
		<link type="text/css" rel="stylesheet" href="/css/navwrap.css" media="screen" />
		<link type="text/css" rel="stylesheet" href="/css/linkbar.css" media="screen" />-->
	
		<!--<script type="text/javascript" src="/js/jquery-1.10.1.min.js"></script>
		<script type="text/javascript" src="/js/jquery-1.12.4.min.js"></script>-->
		<script type="text/javascript" src="/js/jquery-3.5.1.min.js"></script>
				<script type="text/javascript" src="/js/main_linux.js"></script>
		

		



		<!--<script type="text/javascript" src="/js/common.js"></script>
		<script type="text/javascript" src="/js/utils.js"></script>
		<script type="text/javascript" src="/js/date.js"></script>
		<script type="text/javascript" src="/js/lightbox.js"></script>
		<script type="text/javascript" src="/js/legislation.js"></script>
		<script type="text/javascript" src="/js/logon_lits.js"></script>
		<script type="text/javascript" src="/js/message.js"></script>
		<script type="text/javascript" src="/js/comm_meeting.js"></script>-->
		<script type="text/vbscript" src="/vbs/comm_meeting.vbs"></script>
		<!--<script type="text/javascript" src="/js/regs.js"></script>-->
				
	   	<script type="text/javascript">
	    //document.onclick = function () { document.getElementById('transbox').style.display= 'none' };
	    	var xmlhttp=false;
			xmlhttp = create_xml_object();
	
			function getElement(ele)
			{
				var theobj = false;
				if(typeof ele == 'string')
					theobj = (document.getElementById)?document.getElementById(ele):document.all[ele];
				else
					theobj = ele;
			
				return theobj;
			}
		
			function checkreader(friendlyalert)
			{
			 	/*friendlyalert=friendlyalert||false;
			 	
			 	var browser_info = perform_acrobat_detection();
				if (!browser_info.acrobat)
				{
				 	loadadobebox('adobebox', '/adobe.php');
					return false;
				}
				else if (friendlyalert)
				{
			 		alert(friendlyalert);
				}*/
				return true;
			}
				
			function loadadobebox(boxname, url)
			{
				var response = false;
	
				doRequest(xmlhttp, "GET", url, false, null, null);
				if (xmlhttp.status == 200)
				{
		         	response = xmlhttp.responseText;
				}
	
				if(response)
				{
			 		var ele = document.getElementById(boxname);
				 	if (ele)
				 	{
				 		ele.style.visibility = 'hidden';
		 				ele.style.display = 'block';
	
		 				positionElement(ele, 'center', 'center', true);
	
						ele.innerHTML = response;
					    ele.style.visibility = 'visible';
					    ele.style.display = 'block';
	//				    ele.scrollIntoView(true);
					}
				}
				return response;
			}
	
	
			function init()
			{
		 		var ld=document.getElementById("loading");
				if(ld)
				{
					ld.style.display = 'none';
				}
			}
			
			function openmore()
			{
			 	var id = document.getElementById('quicksearch');
			 	if (id)
			 	{
				 	var pos = findPos(id);
				 	id.style.zIndex = 10;
		//		 	id.style.left = pos[0]+'px';
		//		  	id.style.top = pos[1]+'px';
				  	id.style.height = '295px';
				  	id.style.position = 'absolute';
				  	id.style.backgroundColor = '#f7f4ec';
				  	var id2 = document.getElementById('searchmore');
				  	if (id2)
				  	{
				  	 	id2.style.display = 'none';
				  	}
				  	var id3 = document.getElementById('contactlegislatordiv');
				  	if (id3)
				  	{
				  	 	id3.style.display = 'none';
				  	}
				}
			}
		
			function closemore()
			{
			 	var id = document.getElementById('quicksearch');
			 	if (id)
			 	{
				  	id.style.height = '135px';
				  	id.style.position = '';
				  	id.style.backgroundColor = 'transparent';
				  	var id2 = document.getElementById('searchmore');
				  	if (id2)
				  	{
				  	 	id2.style.display = 'block';
				  	}
				  	var id3 = document.getElementById('contactlegislatordiv');
				  	if (id3)
				  	{
				  	 	id3.style.display = '';
				  	}
				}		 	
			}
		
		<!-- This script and many more are available free online at -->
		<!-- The JavaScript Source!! http://javascript.internet.com -->
		
		<!-- Begin
		function right(e) {
		var msg = "Use of this image is strictly prohibited unless express written permission is given to the user by South Carolina Legislative Services Agency.";
		if (navigator.appName == 'Netscape' && e.which == 3) {
		alert(msg);
		return false;
		stopEvent(e);
		}
		if (navigator.appName == 'Microsoft Internet Explorer' && event.button==2) {
		alert(msg);
		return false;
			stopEvent(event);
		}
		else return true;
		}
		
	function trap() 
	{
		if(document.images)
		{
			for(i=0;i<document.images.length;i++)
			{
				if(document.images[i].className == 'allowcontextmenu')
				{
					// this should have no scripting
				}
				else
				{
				 	document.images[i].onmousedown = right;
					document.images[i].oncontextmenu = function(){ return false; };
					//document.images[i].onmouseup = right;
				}
			}
		}
	}

	function findfwtext(texttofind) 
	{
	 	var fwtextele = document.getElementById('fwtext');
		if(fwtextele)
		{
			fwtextele.value = texttofind;
		}
	}	
		// End -->
		</script>

		<!-- ADDED FOR V4 -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-LJY6FMNQKH"></script>


<script type="text/javascript">

//ADDED FOR V4
//Google tag (gtag.js) 
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-LJY6FMNQKH');

 
 /* COMMENTING OUT UPGRADING TO V4 -A
  var _gaq = _gaq || [];
  _gaq.push(['_setAccount', 'UA-36207109-1']);
  _gaq.push(['_setDomainName', 'scstatehouse.gov']);
  _gaq.push(['_setAllowLinker', true]);
  _gaq.push(['_trackPageview']);
 
  (function() {
    var ga = document.createElement('script'); ga.type = 'text/javascript'; ga.async = true;
    ga.src = ('https:' == document.location.protocol ? 'https://ssl' : 'http://www') + '.google-analytics.com/ga.js';
    var s = document.getElementsByTagName('script')[0]; s.parentNode.insertBefore(ga, s);
  })();
*/
  
      $(document).ready(function(){
        // COMMENTING THIS OUT NO LONGER BEING ACTIVELY USED TO MONITOR FOR TRAFFIC TO SPECIFIC LINKS - A
        /*
          var anchors = $('div#contentsection a');

          //console.log('anchors...'+anchors.length);
          if(anchors.length > 0){
            //console.log('setting up event handler...');
            anchors.click(function(){
              var a = $(this).attr('href');
              if(_gaq && (a.substr(-3) == 'htm' || a.substr(-4) == 'html' || a.substr(-3) == 'doc' || a.substr(-4) == 'docx' || a.substr(-3) == 'pdf' || a.substr(-3) == 'xls' || a.substr(-4) == 'xlsx')) {
                //console.log(a);
                _gaq.push(['_trackPageview', $(this).attr('href')]);
              }
              
              var aText = $(this).text().toLowerCase();
              if (a.indexOf('getfile.php') > -1 && aText === 'word'){
                    _gaq.push(['_trackEvent', 'Word Doc', 'Download', ('from page: ' + document.location + ' - href: ' + a)]);
              }

            });
          }
          */
      });

</script>
	</head>
	
		
	<body class="home"  onload="init(); trap();">
	<noscript>Your browser does not support JavaScript!  This page will not render correctly.</noscript> 


	
	<div id="adobebox" style="position:absolute; width:400px; height:150px; border:2px solid #555555; background-color:#cccccc; display:none;"></div>
	<div id="container" >	
				<div id="header" class="nodisplay" style="text-align:center; height:100px;" >
									<img id="headerimg" class="nodisplay" alt="South Carolina Legislature" title="South Carolina Legislature" src="/images/header8.png" />
								
							<!--	<div class="award"><span style="color:#831224; font-weight:bold; font-size:1.5em;">*</span> Recipient of<br>the Notable State Documents Award<br>by the<br>South Carolina<br>State Library.</div>-->
				
				
			</div>
			<div class="printdisplay"><img border="0" src="/images/titleprint.jpg" alt="South Carolina Legislature" title="South Carolina Legislature" alt="South Carolina Legislature" title="South Carolina State Legislature" /><br /><hr /><br /></div>
	
			<div id="pagebody" >
	
	
<!--<div id="topmessage">
<br style="display:block; margin-top:10px;">
Searches and data queries will be unavailable beginning Friday, August 19, 2016, from 8:00 PM until Saturday, August 20th at 8:00 AM<br>due to scheduled maintenance.</div>-->
				<!-- Prompt IE 8/7/6 users to upgrade to a newer browser. -->
				<!--[if lte IE 8]>
				<div class="oldframe">In order to improve your experience using this website, please <a href="http://browsehappy.com/">upgrade your browser</a>.</div>
				<![endif]-->
			
			
			
			<div id="menu" class="nodisplay">
				<ul class="nodisplay">
				<li><a href="/index.php">Home</a></li>
<li><a href="/senate.php">Senate</a></li>
<li><a href="/house.php">House</a></li>
<li><a href="/committeeinfo.php">Committee&nbsp;Postings&nbsp;and&nbsp;Reports</a></li>
<li><a href="/council.php">Legislative Council</a></li>
<li><a href="/citizens.php">Citizens&#39; Interest</a></li>
<li><a href="/publications.php">Publications</a></li>
		    	</ul>
			</div>
			<div id="search" class="nodisplay" style="height: 28px;"><div class="nodisplay" style="float:right; margin:6px 20px 0px 0;">
							<!--<a style="color:#f7f4ec; height:15px;" href="#" onClick="rsswindow();"><img border=0 src="/images/lock.png" style="vertical-align: middle; width: 15px; height: 15px;">&nbsp;Staff&nbsp;Portal</a>-->
<!--				<a style="color:#f7f4ec; height:15px;" href="/splashpage/splashpage.html"><img border=0 src="/images/lock.png" style="vertical-align: middle; width: 15px; height: 15px;">&nbsp;Staff&nbsp;Portal</a> -->
				<a style="color:#f7f4ec; height:15px;" href="/onlineservices/index.php"><img border="0" src="/images/lock.png" style="vertical-align: middle; width: 15px; height: 15px;">&nbsp;Staff&nbsp;Portal</a>
			<!--	<a style="color:#f7f4ec; height:15px;" href="/maintenance_portal.php"><img border=0 src="/images/lock.png" style="vertical-align: middle; width: 15px; height: 15px;">&nbsp;Staff&nbsp;Portal</a>-->
						</div></div>
			
	
					<div id="sidebar" class="nodisplay">
	<div id="vidlinks" style="height: 50px;">
						<!--<img src="/images/videobutton12d.png">-->
											<ul id="vidsidemenu">
	<li id="vidinnermenu" style="font-size:16px; margin: 0 0 5px 0;">Chamber Video</li>
<li id="sbroadcast" style="float: left; width:50%;">
<a id="liveS" style="width: 100%; text-decoration:underline;" href="javascript:void(0);" onClick="live_stream('S', false, false, '0')">Senate</a><br><a id="liveaudioS" style="margin:-3px 0 0 0; text-decoration:underline; width: 100%; font-size: 8px;" href="javascript:void(0);" onClick="live_stream('S', false, false, '1');">(Audio Only)</a>
</li>
<li id="hbroadcast" style="float: left; width:50%;">
<a id="liveH" style="width: 100%; text-decoration:underline;" href="javascript:void(0);" onClick="live_stream('H', false, false, '0')">House</a><br><a id="liveaudioH" style="margin:-3px 0 0 0; text-decoration:underline; width: 100%; font-size: 8px;" href="javascript:void(0);" onClick="live_stream('H', false, false, '1');">(Audio Only)</a>
</li>
						</ul>
					</div>
					<div id="commvidlinks"><a href="/video/schedule.php">Video&nbsp;Schedule</a><a style="border-top:1px solid #fff; padding-top:12px;" href="/video/archives.php">Video Archives</a></div>
										<div id="sidemenu">
						<ul id="innermenu">
		
							<li><a href="/howdoi.php">How do I...</a></li>
										
							
								<li class="nolink" onMouseOver="var ele=document.getElementById('sidesearch'); if(ele){ele.style.display='block'; document.sidesearchform.searchtext.focus();}" onMouseOut="var ele=document.getElementById('sidesearch'); if(ele){ele.style.display='none';}"><div class="nolinkdiv">Quick Search</div>
								<div id="sidesearch" class="sidesubmenu">
									<form id="sidesearchform" name="sidesearchform" method="POST" action="/search.php">
									<input type="hidden" name="search" value="side" />
									<div class="topelement"><label for="searchtext"><span class="label">Search for:</span></label><input id="searchtext" name="searchtext" type="text"/><a id="searchlink2" href="javascript:void(0);" onClick="document.sidesearchform.submit();"><img id="searchicon" src="/images/searchbutton.png" alt="Search" title="Search"/></a></div>
			<!--						<div><input type="checkbox" id="searchchoice_all" name="searchchoice_all" value="all" /><label for="searchchoice_all">All</label></div>-->
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_fullsite" name="category" value="FULLSITE" /><label for="searchchoice_fullsite">&nbsp;Full Site Search</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_billnumber" name="category" value="BILL" /><label for="searchchoice_billnumber">&nbsp;Bill Number</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_legislation" name="category" value="LEGISLATION" CHECKED /><label for="searchchoice_legislation">&nbsp;Legislation</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_budget" name="category" value="BUDGET" /><label for="searchchoice_budget">&nbsp;Budget</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_codeoflaws" name="category" value="CODEOFLAWS" /><label for="searchchoice_codeoflaws">&nbsp;Code of Laws</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_codeofregs" name="category" value="CODEOFREGS" /><label for="searchchoice_codeofregs">&nbsp;Code of Regulations</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_constitution" name="category" value="CONSTITUTION" /><label for="searchchoice_constitution">&nbsp;Constitution</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_housejournals" name="category" value="HOUSEJOURNALS" /><label for="searchchoice_housejournals">&nbsp;House Journals</label></div>
									<div style="padding-left:20px;"><input type="radio" id="searchchoice_senatejournals" name="category" value="SENATEJOURNALS" /><label for="searchchoice_senatejournals">&nbsp;Senate Journals</label></div>
									<div class="bottomelement" style="padding-left:20px;"><input type="radio" id="searchchoice_billsummary" name="category" value="SUMMARY" /><label for="searchchoice_billsummary">&nbsp;LSA Bill Summary</label></div>
								</form>
									
								</div>
							</li>
							<li><a href="/legislatorssearch.php">Find Your Legislators</a></li>
							<li id="contactLegislatorLink"><a href="/email.php?chamber=B">Contact Your Legislator</a></li>
									
							<li><a href="/legislation.php">Legislation</a></li>
							<li><a href="/listtracking/main.php" target="LTS">Track Legislation</a></li>
							<li><a href="/multicriteria2/search.php" target="MCS">Multi-Criteria Search</a></li>
									<!--<li><a href="#" onclick="multisearchwindow('INTROBOTH');">Multi-Criteria Search</a></li>-->
									<!--<li><a href="#" onclick="multisearchwindow('INTROMANUAL');">Multi-Criteria Search</a></li>-->
									<li><a href="/research.php">Research</a></li>
	
								<li class="nolink" onMouseOver="var ele=document.getElementById('law'); if(ele){ele.style.display='block';}" onMouseOut="var ele=document.getElementById('law'); if(ele){ele.style.display='none';}"><div class="nolinkdiv">South Carolina Law</div> 
								<div id="law" class="sidesubmenu">
									<div class="sidediv topelement"><a href="/newlaws.php">Ratifications &amp; Acts</a></div>
									<div class="sidediv"><a href="/code/statmast.php">Code of Laws</a></div>
									<div class="sidediv"><a href="/coderegs/statmast.php">Code of Regulations</a></div>
									<div class="sidediv"><a href="/scconstitution/scconst.php">Constitution</a></div>
									<div class="sidediv bottomelement"><a href="/state_register.php">State Register</a></div>
								</div>
							</li>
										<li class="nolink" onMouseOver="var ele=document.getElementById('manual'); if(ele){ele.style.display='block';}" onMouseOut="var ele=document.getElementById('manual'); if(ele){ele.style.display='none';}"><div class="nolinkdiv">Legislative Manual</div>
								<div id="manual" class="sidesubmenu">
								
<!--									<div class="sidediv topelement"><a href="https://web.sc.gov/LSAShoppingcart/Default.aspx" target="_blank">Purchase Manual</a></div>-->
								
<!--									<div class="sidediv topelement"><a href="https://secure.scstatehouse.gov/cgi-bin/webstore.exe" target="_blank">Purchase Manual</a></div>-->
									<div class="sidediv topelement"><a href="javascript:#" onClick="alert('We are sorry, but we are unable to process online transactions at this time.\n\nIf you would still like to make a purchase, please contact us directly at (803) 212-4490 during normal business hours (8:30am - 5:00pm EST).');">Purchase Manual</a></div>
									<div class="sidediv bottomelement"><a href="/man25/manual25.php">View Manual Online</a></div>
								</div>
							</li>
							<li><a href="http://www.studentconnection.scstatehouse.gov">Student Connection</a></li>
							<li><a href="/visit.php">Visiting the State House</a></li>
							<li><a href="/archives.php">Archives</a></li>
							<li><a href="http://www.sc.gov/Agency-Listing" target="_blank">State Agency Websites</a></li>
							<!--<li><a href="/stateagencysites.php">State Agency Websites</a></li>-->
							<li><a href="/citizensinterestpage/media.php">Media Links</a></li>
				 		</ul>
			    	</div>
	
					<div id="side_ad">
						<A href="http://www.sc.gov/" target="_blank"><img border=0 src="/images/scgov3.jpg" alt="SC.gov" title="SC.gov" /></a>
													<A href="http://www.statelibrary.sc.gov" target="_blank"><img border=0 src="/images/scsl_logo_rgb_web.png" alt="StateLibrary.SC.gov" title="StateLibrary.SC.gov" /></a>
											</div>	    	
			</div>

	
	<script type="text/javascript"> 
		if ( '' === '1'){
		 	
			var link = document.getElementById('contactLegislatorLink');
			if (link != 'undefined' && link != null){
				link.style.display = 'none'; 
				link.style.visibility = 'hidden';
			}
		}
		if ( '' === '1'){
		 	setTimeout(function(){
				var link2 = document.getElementById('sendMsgLink');
				if (link2 != 'undefined' && link2 != null){
					link2.style.display = 'none'; 
					link2.style.visibility = 'hidden';
				};
			}, 20);
			
		}  
	</script>
<div class="mainwidepanel">

				<div id="breadcrumbs">
						South Carolina Law &gt; <a href="/code/statmast.php">Code of Laws</a> &gt; <a href="/code/title1.php">Title 1</a>
				</div>

					<h2 class="barheader">South Carolina Code of Laws<br />
									Unannotated<br />
					</h2>

				<div id="contentsection">
<div style="font-weight: bold; text-align: center;">Title 1 - ADMINISTRATION OF THE GOVERNMENT</div>
<br />

<div style="text-align: center;">CHAPTER 3</div>
<div style="text-align: center;">Governor and Lieutenant Governor</div><br />
<div style="text-align: center;">ARTICLE 1</div>
<div style="text-align: center;">General Provisions Affecting Governor</div><br />
<span style="font-weight: bold;"> SECTION 1-3-10.</span> Departments, agencies and the like shall furnish information requested by Governor.<br /><br />
	The departments, bureaus, divisions, officers, boards, commissions, institutions and other agencies or undertakings of the State, upon request, shall immediately furnish to the Governor, in such form as he may require, any information desired by him in relation to their respective affairs or activities.<br /><br />
HISTORY: 1962 Code SECTION 1-101; 1952 Code SECTION 1-101; 1942 Code SECTION 3216; 1932 Code SECTION 3216; Civ. C. &#39;22 SECTION 912; 1919 (31) 187.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-20.</span> Salary of Governor.<br /><br />
	The Governor shall receive such annual salary as may be provided by the General Assembly.<br /><br />
HISTORY: 1962 Code SECTION 1-102; 1952 Code SECTION 1-102; 1942 Code SECTION 3090; 1932 Code SECTION 3090; Civ. C. &#39;22 SECTION 775; Civ. C. &#39;12 SECTION 691; Civ. C. &#39;02 SECTION 621; G. S. 473; R. S. 537; 1865 (13) 350; 1893 (21) 416; 1919 (31) 4; 1924 (33) 1182; 1948 (45) 1716; 1954 (48) 1566; 1960 (51) 1779; 1963 (53) 358 [478]; 1966 (54) 2424; 1969 (56) 444; 1973 (58) 623.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-30.</span> Executive chamber, official papers and records.<br /><br />
	The Governor shall be furnished with a suitable office, to be called the executive chamber, in which all petitions, memorials, letters and other official papers and documents addressed to or received by him shall be methodically arranged and kept, with proper indexes therefor. He shall keep a record in proper books of:<br /><br />
	(1) All his messages to the General Assembly;<br /><br />
	(2) All bills presented to him in obedience to the provisions of the Constitution and all objections he may make to any of them;<br /><br />
	(3) All official communications, proclamations and orders issuing from his office; and<br /><br />
	(4) All other matters which he may think it important to preserve.<br /><br />
HISTORY: 1962 Code SECTION 1-103; 1952 Code SECTION 1-103; 1942 Code SECTION 3090; 1932 Code SECTION 3090; Civ. C. &#39;22 SECTION 775; Civ. C. &#39;12 SECTION 691; Civ. C. &#39;02 SECTION 621; G. S. 473; R. S. 537; 1865 (13) 350; 1893 (21) 416; 1919 (31) 4; 1924 (33) 1182.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-40.</span> Private secretary of Governor.<br /><br />
	The Governor shall be allowed a private secretary, to be appointed by him, who shall under the direction of the Governor keep an accurate record under proper dates of all transactions, opinions and other official matters and acts occurring during his period of office. Said record shall, under certain restrictions, be open to the inspection of the members of the General Assembly. He shall also perform such clerical and other duties as may be required of him by the Governor, in connection with the duties of the office of Governor.<br /><br />
HISTORY: 1962 Code SECTION 1-104; 1952 Code SECTION 1-104; 1942 Code SECTION 3091; 1932 Code SECTION 3901; Civ. C. &#39;22 SECTION 776; Civ. C. &#39;12 SECTION 692; Civ. C. &#39;02 SECTION 622; G. S. 474; R. S. 538; 1865 (13) 350; 1868 (14) 11; 1869 (14) 246; 1893 (21) 416.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-50.</span> Personal staff of Governor for ceremonial occasions; military secretary.<br /><br />
	Whenever the Governor shall desire the attendance of a personal staff upon any ceremonial occasion he shall detail therefor such officers as he may choose from the active list of the National Guard of South Carolina, resident in or nearest to the place where such ceremonies are to be held, and the officers detailed shall attend in uniform at the time and place designated and shall constitute the personal staff of the Governor for that occasion, reverting upon completion of such duty to their regular assignments. The Governor may appoint as his military secretary any officer of the United States Army detailed for duty with the militia of this State, and such officer shall have the rank of colonel and the title &quot;Military Secretary to the Governor&quot;.<br /><br />
HISTORY: 1962 Code SECTION 1-105; 1952 Code SECTION 1-105; 1950 (46) 1881.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-60.</span> Governor designation of agency to administer South Carolina Developmental Disabilities Council.<br /><br />
	The Governor shall designate, by executive order, the appropriate agency to administer the South Carolina Developmental Disabilities Council in accordance with the Federal Developmental Disabilities Act of 2000, Pub. Law 106-402. The Department of Administration shall provide such administrative support to the Developmental Disabilities Council as it may request and require in the performance of its duties, including, but not limited to, financial accounting support, human resources administrative support, information technology shared services support, procurement services, and logistical support.<br /><br />
HISTORY: 2018 Act No. 160 (S.805), SECTION 13, eff July 1, 2019.<br /><br />
Editor&#39;s Note<br /><br />
	2018 Act No. 160, SECTIONS 18.A and 18.B, provide as follows:<br /><br />
	&quot;SECTION 18. A. Where the provisions of this act transfer duties, programs, or services of the Department of Administration to the Department of Children&#39;s Advocacy, the employees, authorized appropriations, and assets and liabilities of these divisions, services, and programs also are transferred to and become part of the Department of Children&#39;s Advocacy. All classified or unclassified personnel employed by the divisions, programs, services, or initiatives transferred from the Department of Administration, either by contract or by employment at will, become on July 1, 2019, employees of the Department of Children&#39;s Advocacy, with the same compensation, classification, and grade level, as applicable. Before the transfer of the applicable divisions, programs, services, or initiatives of the Department of Administration pursuant to this act, these agencies and organizations shall cause all necessary actions to be taken to accomplish this transfer in accordance with state and federal laws and regulations.<br /><br />
	&quot;B. Applicable regulations promulgated by the Department of Administration are continued and are considered to be promulgated by the Department of Children&#39;s Advocacy. Applicable contracts entered into by the Department of Administration are continued and are considered to be devolved upon the Department of Children&#39;s Advocacy at the time of the transfer.&quot;<br /><br />
<div style="text-align: center;">ARTICLE 3</div>
<div style="text-align: center;">Installation of Governor; Vacancy in Office</div><br />
<span style="font-weight: bold;"> SECTION 1-3-110.</span> Date of installation of Governor.<br /><br />
	The Governor shall be installed on the first Wednesday following the second Tuesday in January following his election; but in case the Governor is unable to be installed on the day herein provided, he shall be installed as soon thereafter as is practicable.<br /><br />
HISTORY: 1962 Code SECTION 1-111; 1952 Code SECTION 1-111; 1942 Code SECTION 3085; 1932 Code SECTION 3085; Civ. C. &#39;22 SECTION 770; Civ. C. &#39;12 SECTION 686; 1911 (27) 142; 1979 Act No. 29, SECTION 1.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-120.</span> Vacancy in office of both Governor and Lieutenant Governor.<br /><br />
	In case of the removal, death, resignation or disability of both the Governor, and the Lieutenant Governor, the President of the Senate shall perform the duties and exercise the powers of Governor until such disability of the Governor or Lieutenant Governor has been removed or until the next general election, at which a Governor must be elected by the electors duly qualified, as prescribed by Section 3, Article IV of the Constitution and the general state statutory law.<br /><br />
HISTORY: 1962 Code SECTION 1-112; 1952 Code SECTION 1-112; 1942 Code SECTION 3086; 1932 Code SECTION 3086; Civ. C. &#39;22 SECTION 771; Civ. C. &#39;12 SECTION 687; Civ. C. &#39;02 SECTION 617; G. S. 469; R. S. 533; 1868 (14) 101; 2019 Act No. 1 (S.2), SECTION 1, eff January 31, 2019.<br /><br />
Effect of Amendment<br /><br />
	2019 Act No. 1, SECTION 1, substituted &quot;President of the Senate&quot; for &quot;President of the Senate pro tempore&quot;, &quot;of the Governor or Lieutenant Governor has&quot; for &quot;shall have&quot;, &quot;Governor must&quot; for &quot;Governor shall&quot;, and &quot;as prescribed by Section 3, Article IV of the Constitution and the general state statutory law&quot; for &quot;as is prescribed by Section 3 of Article IV of the Constitution&quot;.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-125.</span> Filling vacancy in office of Lieutenant Governor.<br /><br />
	Beginning with the Lieutenant Governor elected in the 2018 General Election, in the case of the Lieutenant Governor&#39;s impeachment, death, resignation, disqualification, disability, or removal from the State, the Governor, with the advice and consent of the Senate, shall appoint a successor to fulfill the unexpired term.<br /><br />
HISTORY: 2018 Act No. 142 (H.4977), SECTION 1, eff March 15, 2018.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-130.</span> Disability of Governor, Lieutenant Governor and President of Senate.<br /><br />
	In case of the disability, from whatever cause, of the Governor, the Lieutenant Governor, and the President of the Senate, the Speaker of the House of Representatives shall perform the duties and exercise the powers of Governor, in like manner and upon like conditions as are prescribed in Section 1-3-120.<br /><br />
HISTORY: 1962 Code SECTION 1-113; 1952 Code SECTION 1-113; 1942 Code SECTION 3087; 1932 Code SECTION 3087; Civ. C. &#39;22 SECTION 772; Civ. C. &#39;12 SECTION 688; Civ. C. &#39;02 SECTION 618; G. S. 470; R. S. 534; 1868 (14) 102; 2019 Act No. 1 (S.2), SECTION 2, eff January 31, 2019.<br /><br />
Effect of Amendment<br /><br />
	2019 Act No. 1, SECTION 2, substituted &quot;President of the Senate&quot; for &quot;President of the Senate pro tempore&quot;, and made nonsubstantive changes.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-140.</span> Disability of all of officers enumerated in SECTIONSECTION 1-3-120 and 1-3-130.<br /><br />
	In case of the disability, from whatever cause, of all of the officers enumerated in SECTIONS 1-3-120 and 1-3-130, the General Assembly, if it shall be in session, by a joint vote shall elect a person duly qualified to fill the office of Governor in like manner, and upon the like conditions, as are prescribed by SECTION 1-3-120.<br /><br />
HISTORY: 1962 Code SECTION 1-114; 1952 Code SECTION 1-114; 1942 Code SECTION 3088; 1932 Code SECTION 3088; Civ. C. &#39;22 SECTION 773; Civ. C. &#39;12 SECTION 689; Civ. C. &#39;02 SECTION 619; G. S. 471; R. S. 535; 1868 (14) 102.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-150.</span> Term of Governor elected pursuant to SECTION 1-3-140.<br /><br />
	Whenever a Governor shall be elected as provided in SECTION 1-3-140, he shall immediately enter upon the discharge of the duties of his office and shall continue to discharge them during the residue of the term.<br /><br />
HISTORY: 1962 Code SECTION 1-115; 1952 Code SECTION 1-115; 1942 Code SECTION 3089; 1932 Code SECTION 3089; Civ. C. &#39;22 SECTION 774; Civ. C. &#39;12 SECTION 690; Civ. C. &#39;02 SECTION 620; G. S. 472; R. S. 536; 1868 (14) 102.<br /><br />
<div style="text-align: center;">ARTICLE 5</div>
<div style="text-align: center;">Appointment and Removal of Officers</div><br />
<span style="font-weight: bold;"> SECTION 1-3-210.</span> Filling vacancies when Senate not in session.<br /><br />
	During the recess of the Senate, vacancy which occurs in an office filled by an appointment of the Governor with the advice and consent of the Senate may be filled by an interim appointment of the Governor. The Governor must report the interim appointment to the Senate and must forward a formal appointment at its next ensuing regular session.<br /><br />
	If the Senate does not advise and consent thereto prior to sine die adjournment of the next ensuing regular session, the office shall be vacant and the interim appointment shall not serve in hold over status notwithstanding any other provision of law to the contrary. A subsequent interim appointment of a different person to a vacancy created by a failure of the Senate to grant confirmation to the original interim appointment shall expire on the second Tuesday in January following the date of such subsequent interim appointment and the office shall be vacant.<br /><br />
HISTORY: 1962 Code SECTION 1-121; 1952 Code SECTION 1-121; 1942 Code SECTION 3093; 1932 Code SECTION 3093; Civ. C. &#39;22 SECTION 778; Civ. C. &#39;12 SECTION 694; Civ. C. &#39;02 SECTION 624; G. S. 476, 477; R. S. 540; 1868 (14) 66; 1870 (14) 376; 1871 (15) 690; 1876 (16); 1877 (16) 249; 1878 (16) 571, 609, 766; 1882 (18) 1111; 1890 (20) 697; 1896 (22) 154; 1901 (23) 701; 1920 (31) 704, 908; 1922 (32) 938; 1945 (44) 156; 1954 (48) 1745; Const. 1895, Art. 12, SECTION 2; 1963 (53) 512; 1993 Act No. 181, SECTION 3.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-215.</span> Appointments by the Governor requiring advice and consent of Senate.<br /><br />
	(A) Appointments by the Governor requiring the advice and consent of the Senate must be transmitted to the Senate and must contain at a minimum the following information:<br /><br />
	(1) the title of the office to which the individual is being appointed;<br /><br />
	(2) the designation of any special seat, discipline, interest group or other designated entity that the individual is representing or is chosen from;<br /><br />
	(3) the full legal name of the individual being appointed;<br /><br />
	(4) the current street or mailing address and telephone number;<br /><br />
	(5) the county, counties, district or other geographic area or political subdivision being represented;<br /><br />
	(6) the name of the individual being replaced if the appointment is not an initial appointment; and<br /><br />
	(7) the commencement and ending date of the term of office.<br /><br />
	(B) When an appointment has been confirmed by the Senate, evidence of such confirmation shall be transmitted to the Secretary of State by the Clerk of the Senate and the Secretary of State must thereafter obtain the necessary oath and evidence of bond if required. The taking of the oath of office and filing of any requisite bond shall fully vest the person appointed with the full rights, privileges and powers of the office. The notice of confirmation transmitted by the Senate shall be conclusive as to the validity of an appointment and the issuance of a commission by the Secretary of State after obtaining the requisite documentation is a ministerial act.<br /><br />
HISTORY: 1993 Act No. 183, SECTION 4; 1993 Act No. 181, SECTION 4.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-220.</span> Appointment of certain officers by Governor.<br /><br />
	The following appointments shall be made by the Governor and are in addition to those appointments by the Governor authorized in other provisions in the Code:<br /><br />
	(1) An appointment to fill any vacancy in an office of the executive department as defined in Section 1-1-110 occurring during a recess of the General Assembly. The term of such appointment shall be until the vacancy be filled by a general election or by the General Assembly in the manner provided by law.<br /><br />
	(2) An appointment to fill any vacancy in a county office. The person so appointed shall hold office, in all cases in which the office is elective, until the next general election and until his successor shall qualify; and in the case of offices originally filled by appointment and not by election, until the adjournment of the session of the General Assembly next after such vacancy has occurred. The Governor may remove for cause any person so appointed by him under the provisions of this paragraph to fill any such vacancy.<br /><br />
	(3) Proxies to represent the share of the State in the Cheraw and Coalfields Railroad Company and in the Cheraw and Salisbury Railroad Company.<br /><br />
	(4) The chief constable of the State, whensoever in his judgment any public emergency shall require it or when necessary to the due execution of legal process.<br /><br />
HISTORY: 1962 Code SECTION 1-122; 1952 Code SECTION 1-122; 1942 Code SECTION 3094; 1932 Code SECTION 3094; Civ. C. &#39;22 SECTION 779; Civ. C. &#39;02 SECTION 625; G. S. 477; R. S. 541; 1818 (16) 723; 1840 (11) 147; 1875 (15) 935; 1877 (16) 263; 1878 (16) 656, 716; 1884 (18) 691; 1903 (24) 19; 1960 (51) 1917; 1993 Act No. 181, SECTION 5.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-230.</span> Appointment of poet laureate.<br /><br />
	Upon the recommendation of qualified candidates by the South Carolina Arts Commission, the Governor shall name and appoint an outstanding and distinguished person of letters as poet laureate for the State of South Carolina for a term of four years and until a successor has been appointed and qualified. A poet laureate is eligible for reappointment one time. The poet laureate shall respond to requests of the Governor and participate in other relevant public programming.<br /><br />
HISTORY: 1962 Code SECTION 1-123; 1952 Code SECTION 1-123; 1942 Code SECTION 3094; 1932 Code SECTION 3094; Civ. C. &#39;22 SECTION 779; Civ. C. &#39;12 SECTION 695; Civ. C. &#39;02 SECTION 625; G. S. 477; R. S. 541; 1875 (15) 935; 1909 (26) 127; 1911 (27) 5; 1924 (33) 1016; 1933 (38) 296; 1934 (38) 1299; 2018 Act No. 153 (S.340), SECTION 1, eff April 17, 2018.<br /><br />
Effect of Amendment<br /><br />
	2018 Act No. 153, SECTION 1, rewrote the section, providing that the South Carolina Arts Commission shall provide the Governor with recommendations of qualified candidates and establishing terms of office and duties.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-240.</span> Removal of officers by Governor.<br /><br />
	(A) Any officer of the county or State, except:<br /><br />
	(1) an officer whose removal is provided for in Section 3 of Article XV of the State Constitution;<br /><br />
	(2) an officer guilty of the offense named in Section 8 of Article VI of the State Constitution; or<br /><br />
	(3) pursuant to subsection (B) of this section, an officer of the State appointed by the Governor, either with or without the advice and consent of the Senate; who is guilty of malfeasance, misfeasance, incompetency, absenteeism, conflicts of interest, misconduct, persistent neglect of duty in office, or incapacity must be subject to removal by the Governor upon any of the foregoing causes being made to appear to the satisfaction of the Governor. Before removing any such officer, the Governor shall inform him in writing of the specific charges brought against him and give him an opportunity on reasonable notice to be heard.<br /><br />
	(B) A person appointed to a state office by the Governor, either with or without the advice and consent of the Senate, other than those officers enumerated in subsection (C), may be removed from office by the Governor at his discretion by an Executive Order removing the officer.<br /><br />
	(C)(1) Persons appointed to the following offices of the State may be removed by the Governor for malfeasance, misfeasance, incompetency, absenteeism, conflicts of interest, misconduct, persistent neglect of duty in office, or incapacity:<br /><br />
	(a) Workers&#39; Compensation Commission;<br /><br />
	(b) [Reserved]<br /><br />
	(c) Ethics Commission;<br /><br />
	(d) Election Commission;<br /><br />
	(e) Professional and Occupational Licensing Boards;<br /><br />
	(f) Juvenile Parole Board;<br /><br />
	(g) Probation, Parole and Pardon Board;<br /><br />
	(h) Director of the Department of Public Safety;<br /><br />
	(i) Board of the Department of Health and Environmental Control, excepting the chairman;<br /><br />
	(j) Chief of State Law Enforcement Division;<br /><br />
	(k) South Carolina Lottery Commission;<br /><br />
	(l) Executive Director of the Office of Regulatory Staff;<br /><br />
	(m) Directors of the South Carolina Public Service Authority appointed pursuant to Section 58-31-20;<br /><br />
	(n) State Ports Authority;<br /><br />
	(o) State Inspector General;<br /><br />
	(p) State Adjutant General;<br /><br />
	(q) South Carolina Retirement Investment Commission members appointed by the Governor or members of the General Assembly; and<br /><br />
	(r) South Carolina Public Benefit Authority members.<br /><br />
	(2) Upon the expiration of an officeholder&#39;s term, the individual may continue to serve until a successor is appointed and qualifies.<br /><br />
HISTORY: 1962 Code SECTION 1-124; 1952 Code SECTION 1-124; 1942 Code SECTION 3098; 1932 Code SECTION 3098; 1924 (33) 997; 1993 Act No. 181, SECTION 6; 2001 Act No. 59, SECTION 3; 2004 Act No. 175, SECTION 1, eff March 4, 2004; 2005 Act No. 137, SECTION 1, eff May 25, 2005; 2007 Act No. 114, SECTION 3, eff June 27, 2007; 2009 Act No. 73, SECTION 16, eff June 16, 2009; 2012 Act No. 105, SECTION 1, eff January 1, 2012; 2014 Act No. 224 (H.3540), SECTION 1, eff March 5, 2015; 2016 Act No. 275 (S.1258), SECTION 86, eff July 1, 2016; 2017 Act No. 13 (H.3726), Pt. V, SECTION 16, eff July 1, 2017; 2021 Act No. 90 (H.3194), SECTION 6, eff June 15, 2021.<br /><br />
Code Commissioner&#39;s Note<br /><br />
	At the direction of the Code Commissioner, the repeal of (C)(1)(b) by 2016 Act No. 275, SECTION 86, was changed to &quot;Reserved&quot;.<br /><br />
Editor&#39;s Note<br /><br />
	2014 Act No. 224, SECTION 4, provides as follows:<br /><br />
	&quot;SECTION 4. This act takes effect upon the ratification of amendments to Section 7, Article VI, and Section 4, Article XIII of the Constitution of this State deleting the requirement that the Adjutant General be elected by the qualified electors of this State and providing that he be appointed by the Governor.&quot;<br /><br />
	2015 Act No. 1 (S.8) SECTIONS 1.A, 1.B, eff March 5, 2015, ratified amendments to Section 7, Article VI, and Section 4, Article XIII of the Constitution.<br /><br />
Effect of Amendment<br /><br />
	The 2004 amendment added subsection (C)(12).<br /><br />
	The 2005 amendment, in subsection (C), designated paragraph (1) and under it redesignated items (1) to (12) as subparagraphs (a) to (l), in subparagraph (b), substituted &quot;Reserved&quot; for &quot;Commission of the Department of Revenue&quot;, and added subparagraph (m) relating to the officers who may be removed by the governor; and designated paragraph (2) making nonsubstantive changes.<br /><br />
	The 2007 amendment, in subsection (C)(1)(b), substituted &quot;Department of Transportation Commission&quot; for &quot;Reserved&quot;.<br /><br />
	The 2009 amendment added subsection (C)(1)(n) relating to State Ports Authority.<br /><br />
	The 2012 amendment inserted subsection (C)(1)(o) and made other nonsubstantive changes.<br /><br />
	2014 Act No. 224, SECTION 1, effective March 5, 2015, added subsection (C)(1)(p), relating to the Adjutant General.<br /><br />
	2016 Act No. 275, SECTION 86, repealed (C)(1)(b), relating to the Department of Transportation Commission.<br /><br />
	2017 Act No. 13, Pt. V, SECTION 16, added (C)(1)(q) and (C)(1)(r), and made other nonsubstantive changes.<br /><br />
	2021 Act No. 90, SECTION 6, in (C)(1)(m), deleted the second, third, and fourth sentences, clarifying the Governor&#39;s authority to remove directors of the Public Service Authority.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-245.</span> Removal from office of member of state board for three consecutive unexcused absences; vacancy created; requirement of chairman to notify appointing authority; exclusion for ex officio member or designee.<br /><br />
	(A) A member of a state board, council, commission, or committee who has three consecutive unexcused absences from regularly scheduled meetings held by the particular board, council, commission, or committee is considered removed from the board, council, commission, or committee and a vacancy is created. The chairman of the board, council, commission, or committee immediately shall notify the Governor or appropriate appointing authority of the member&#39;s three consecutive unexcused absences and of the resulting vacancy. An unexcused absence must be defined by each respective board, council, commission, or committee in rules governing its operation.<br /><br />
	(B) This section does not apply to an ex officio member of a state board, council, commission, or committee or to a designee of an ex officio member.<br /><br />
HISTORY: 1995 Act No. 79, SECTION 1.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-250.</span> Appeal by officer removed by Governor.<br /><br />
	An officer, other than a state officer appointed by the Governor pursuant to subsection (B) of Section 1-3-240, shall have the right of appeal from any order of removal by the Governor under Section 1-3-240 to the resident or presiding judge of the circuit in which the officer resides. The judge shall hear and determine the appeal both as to law and fact upon the record as made before the Governor and upon additional evidence as he shall see fit to allow. The notice of appeal shall be served upon the Governor, or his secretary, within five days after the service upon the officer of the order of the Governor removing him and shall state the grounds for the appeal and name the circuit judge to whom the appeal is taken. The Governor shall transmit to the judge the record in the case, including a copy of the order of removal, grounds of removal, evidence in support of removal and return of service, and any other matter which in his judgment may be considered by the court. The circuit judge within twenty days after the taking of the appeal, or in such shorter time as may be practical, shall hear and determine the appeal, after giving to the parties reasonable notice of the time and place of hearing. The hearing may be had and judgment may be rendered in open court, or at chambers within or without the circuit. Any appeal from the order of the circuit court must be taken in the manner provided by the South Carolina Appellate Court Rules.<br /><br />
HISTORY: 1962 Code SECTION 125; 1952 Code SECTION 1-125; 1942 Code SECTION 3098; 1932 Code SECTION 3098; 1924 (33) 997; 1960 (51) 1736; 1993 Act No. 181, SECTION 7; 1999 Act No. 55, SECTION 1.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-260.</span> Removal procedure as additional to other removal procedures.<br /><br />
	The power and procedure of removal conferred and provided for in SECTIONS 1-3-240 and 1-3-250 are additional to any other removal powers or procedure authorized by statute.<br /><br />
HISTORY: 1962 Code SECTION 1-126; 1952 Code SECTION 1-126; 1942 Code SECTION 3098; 1932 Code SECTION 3098; 1924 (33) 997.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-270.</span> Filling of vacancies created by removal pursuant to SECTION 1-3-240.<br /><br />
	Any vacancy created under the authority vested by SECTION 1-3-240 shall be filled as provided by the Constitution and statute laws of the State relating to the filling of a vacancy in the office in which such vacancy is so created.<br /><br />
HISTORY: 1962 Code SECTION 1-127; 1952 Code SECTION 1-127; 1942 Code SECTION 3098; 1932 Code SECTION 3098; 1924 (33) 997.<br /><br />
<div style="text-align: center;">ARTICLE 7</div>
<div style="text-align: center;">Maintenance of Peace and Order</div><br />
<span style="font-weight: bold;"> SECTION 1-3-410.</span> Governor may act to prevent violence.<br /><br />
	The Governor may take such measures and do all and every act and thing which he may deem necessary in order to prevent violence or threats of violence to the person or property of citizens of the State and to maintain peace, tranquility and good order in the State, and in any political subdivision thereof, and in any particular area of the State designated by him.<br /><br />
HISTORY: 1962 Code SECTION 1-128; 1957 (50) 521.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-420.</span> Proclamation of emergency by Governor.<br /><br />
	The Governor, when in his opinion the facts warrant, shall, by proclamation, declare that, because of unlawful assemblage, violence or threats of violence, or a public health emergency, as defined in Section 44-4-130, a danger exists to the person or property of any citizen and that the peace and tranquility of the State, or any political subdivision thereof, or any particular area of the State designated by him, is threatened, and because thereof an emergency, with reference to such threats and danger, exists.<br /><br />
	The Governor, upon the issuance of a proclamation as provided for in this section, must immediately file the proclamation in the Office of the Secretary of State, which proclamation is effective upon issuance and remain in full force and effect until revoked by the Governor.<br /><br />
HISTORY: 1962 Code SECTION 1-129; 1957 (50) 521; 2002 Act No. 339, SECTION 3.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-430.</span> Orders to prevent danger.<br /><br />
	In all such cases when the Governor shall issue his proclamation as provided in SECTION 1-3-420 he may further, cope with such threats and danger, order and direct any person or group of persons to do any act which would in his opinion prevent or minimize danger to life, limb or property, or prevent a breach of the peace; and he may order any person or group of persons to refrain from doing any act or thing which would, in his opinion, endanger life, limb or property, or cause, or tend to cause, a breach of the peace, or endanger the peace and good order of the State or any section or community thereof, and he shall have full power by use of all appropriate available means to enforce such order or proclamation.<br /><br />
HISTORY: 1962 Code SECTION 1-130; 1957 (50) 521.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-440.</span> Further powers of Governor.<br /><br />
	For the purposes already stated the Governor may take and exercise any or all of the following actions:<br /><br />
	(1) Call out the military forces of the State (State militia) or any unit or units thereof and order and direct them to take such action as in his judgment may be necessary to avert any threatened danger and to maintain peace and good order;<br /><br />
	(2) Order any and all law enforcement officers of the State or any of its subdivisions to do whatever may be deemed necessary to maintain peace and good order;<br /><br />
	(3) Order the discontinuance of any transportation or other public facilities, or, in the alternative, direct that such facilities be operated by a State agency; or<br /><br />
	(4) Authorize, order or direct any State, county or city official to enforce the provisions of such proclamation in the courts of the State by injunction, mandamus, or other appropriate legal action.<br /><br />
HISTORY: 1962 Code SECTION 1-130.1; 1957 (50) 521.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-450.</span> Intervention by Governor in situations of violence or public disorder.<br /><br />
	The Governor may intervene in any situation where there exists violence or threats of violence to persons or property and take complete control thereof to prevent violence, riotous conduct, public disorder or breaches of the peace.<br /><br />
HISTORY: 1962 Code SECTION 1-30.2; 1957 (50) 521.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-460.</span> Governor&#39;s powers under article shall be supplemental to powers granted by other laws of State.<br /><br />
	The powers granted in this article are supplemental to and in aid of powers now vested in the Governor under the Constitution, statutory laws and police powers of the State.<br /><br />
HISTORY: 1962 Code SECTION 1-30.3; 1957 (50) 521.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-470.</span> Lowering flags upon death in line of duty of firefighter or law enforcement officer.<br /><br />
	The Governor on the day of burial or other service for any firefighter or law enforcement officer in this State who died in the line of duty shall order all flags on state buildings to be flown at half-mast in tribute to the deceased firefighter or law enforcement officer. The Governor shall also request that flags over the buildings of the political subdivisions of this State similarly be flown at half-mast for this purpose.<br /><br />
HISTORY: 1987 Act No. 104, SECTION 1.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-480.</span> Authority of Governor to authorize national guard to support federal, state and local law enforcement agencies in drug enforcement matters; delegation of authority.<br /><br />
	(A) The Governor, as Commander-in-Chief of the organized militia of this State and in accordance with Title 32, United States Code, Section 112, may authorize or direct the South Carolina National Guard to assist and support federal, state, and local law enforcement agencies in drug interdiction, counterdrug activities, and demand reduction activities. The Governor may delegate his authority under this section to the Adjutant General who is specifically authorized to enter into mutual assistance and support agreements with law enforcement agencies operating within this State for activities within this State.<br /><br />
	(B) The Governor, with the consent of Congress, is authorized to enter into compacts and agreements for the deployment of the National Guard with governors of other states concerning drug interdiction, counterdrug activities, and demand reduction activities. To facilitate these agreements, the General Assembly ratifies the National Guard Mutual Assistance Counterdrug Activities Compact, codified at Section 1-3-490. Article I, Section 10 of the Constitution of the United States permits a state to enter into a compact or agreement with another state, subject to the consent of Congress. Congress, through enactment of 4 U.S.C. Section 112, has given its consent for states to enter such compacts for cooperative effort and mutual assistance in the prevention of crime.<br /><br />
HISTORY: 1992 Act No. 379, SECTION 1; 1995 Act No. 113, SECTION 1.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-490.</span> National Guard Mutual Assistance Counterdrug Activities Compact.<br /><br />
	The National Guard Mutual Assistance Counterdrug Activities Compact is hereby enacted into law and entered into by the State of South Carolina with all other states legally joining, in the form substantially as follows:<br /><br />
	THE NATIONAL GUARD MUTUAL ASSISTANCE COUNTERDRUG ACTIVITIES COMPACT<br /><br />
<div style="text-align: center;">ARTICLE I</div>
<div style="text-align: center;">Purpose</div><br />
	The purposes of this compact are to:<br /><br />
	(A) provide for mutual assistance and support among the party states in the utilization of the National Guard in drug interdiction, counterdrug activities, and demand reduction activities;<br /><br />
	(B) permit the National Guard of this State to enter into mutual assistance and support agreements, on the basis of need, with one or more law enforcement agencies operating within this State, for activities within this State, or with a National Guard of one or more other states, whether the activities are within or outside this State in order to facilitate and coordinate efficient, cooperative enforcement efforts directed toward drug interdiction, counterdrug activities, and demand reduction activities;<br /><br />
	(C) permit the National Guard of this State to act as a receiving and a responding state as defined within this compact and to ensure the prompt and effective delivery of National Guard personnel, assets, and services to agencies or areas that are in need of increased support and presence;<br /><br />
	(D) permit and encourage a high degree of flexibility in the deployment of National Guard forces in the interest of efficiency;<br /><br />
	(E) maximize the effectiveness of the National Guard in situations which permit its utilization under this compact;<br /><br />
	(F) provide protection for the rights of National Guard personnel when performing duty in other states in counterdrug activities; and<br /><br />
	(G) ensure uniformity of state laws in the area of National Guard involvement in interstate counterdrug activities by incorporating the uniform laws within the compact.<br /><br />
<div style="text-align: center;">ARTICLE II</div>
<div style="text-align: center;">Entry into Force and Withdrawal</div><br />
	(A) This compact becomes effective when enacted by any two states. Thereafter, this compact becomes effective as to another state upon its enactment.<br /><br />
	(B) A party state may withdraw from this compact by enacting a statute repealing the compact, but no withdrawal shall take effect until one year after the governor of the withdrawing state has given notice in writing of the withdrawal to the governors of all other party states.<br /><br />
<div style="text-align: center;">ARTICLE III</div>
<div style="text-align: center;">Mutual Assistance and Support</div><br />
	(A) As used in this article:<br /><br />
	(1) &quot;Drug interdiction and counterdrug activities&quot; means the use of National Guard personnel, while not in federal service, in law enforcement support activities that are intended to reduce the supply or use of illegal drugs in the United States. These activities include, but are not limited to:<br /><br />
	(a) providing information obtained during either the normal course of military training or operations or during counterdrug activities to federal, state, or local law enforcement officials that may be relevant to a violation of a federal or state law within the jurisdiction of these officials;<br /><br />
	(b) making available equipment, including associated supplies or spare parts, base facilities, or research facilities of the National Guard to a federal, state, or local civilian law enforcement official for law enforcement purposes, in accordance with other applicable law;<br /><br />
	(c) providing available National Guard personnel to train federal, state, or local civilian law enforcement in the operation and maintenance of equipment, including equipment made available pursuant to this provision, in accordance with other applicable law;<br /><br />
	(d) providing available National Guard personnel to operate and maintain equipment provided to federal, state, or local law enforcement officials pursuant to activities defined and referred to in this compact;<br /><br />
	(e) operation and maintenance of equipment and facilities of the National Guard or law enforcement agencies used for the purposes of drug interdiction and counterdrug activities;<br /><br />
	(f) providing available National Guard personnel to operate equipment for the detection, monitoring, and communication of the movement of air, land, and sea traffic, to facilitate communications in connection with law enforcement programs, to provide transportation for civilian law enforcement personnel;<br /><br />
	(g) providing available National Guard personnel, equipment, and support for administrative, interpretive, analytic, or other purposes;<br /><br />
	(h) providing available National Guard personnel and other equipment to aid federal, state, and local officials and agencies otherwise involved in the prosecution or incarceration of individuals processed within the criminal justice system who have been arrested for criminal acts involving the use, distribution, or transportation of controlled substances as defined in 21 U.S.C. 801 et seq. or in accordance with other applicable law.<br /><br />
	(2) &quot;Demand reduction&quot; means providing available National Guard personnel, equipment, support, and coordination to federal, state, local, and civic organizations and agencies for the purposes of the prevention of drug abuse and the reduction in the demand for illegal drugs.<br /><br />
	(3) &quot;Requesting state&quot; means the state whose governor requested assistance in the area of counterdrug activities.<br /><br />
	(4) &quot;Responding state&quot; means the state furnishing assistance, or requested to furnish assistance, in the area of counterdrug activities.<br /><br />
	(5) &quot;Law enforcement agency&quot; means a lawfully established federal, state, or local public agency that is responsible for the prevention and detection of crime and the enforcement of penal, traffic, regulatory, game, immigration, postal, customs, or controlled substances laws.<br /><br />
	(6) &quot;Official&quot; means the appointed, elected, or designated representative of an agency, institution, or organization authorized to conduct those activities for which support is requested.<br /><br />
	(7) &quot;Mutual assistance and support agreement&quot; means an agreement between the National Guard of this State and one or more law enforcement agencies or between the National Guard of this State and the National Guard of one or more other states, consistent with the purposes of this compact.<br /><br />
	(8) &quot;Party state&quot; means a state that has lawfully enacted this compact.<br /><br />
	(9) &quot;State&quot; means each of the several states of the United States, the District of Columbia, the Commonwealth of Puerto Rico, or a territory or possession of the United States.<br /><br />
	(B) Upon the request of the governor of a party state for assistance in drug interdiction, counterdrug activities, and demand reduction activities, the governor of a responding state shall have authority under this compact to send to a requesting state and place under the temporary operational control of the appropriate National Guard or military authorities of that state, for the purposes of providing the requested assistance, all or a part of the National Guard forces of his state. The exercise of his discretion in this regard must be conclusive.<br /><br />
	(C) The governor of a party state may withhold the National Guard forces of his state from deployment in a requesting state and recall the forces deployed in a requesting state.<br /><br />
	(D) The National Guard of this State is authorized to engage in counterdrug activities and demand reduction activities.<br /><br />
	(E) The Adjutant General of this State, in order to further the purposes of this compact, may enter into a mutual assistance and support agreement with one or more law enforcement agencies of this State, and with the National Guard of other party states to provide personnel, assets, and services in the area of counterdrug activities and demand reduction activities provided that all parties to the agreement are not specifically prohibited by law to perform these activities.<br /><br />
	(F) The agreement must set forth the powers, rights, and obligations of the parties to the agreement, where applicable, as follows:<br /><br />
	(1) the duration of the agreement;<br /><br />
	(2) the organization, composition, and nature of a separate legal entity created by the agreement;<br /><br />
	(3) the purpose of the agreement;<br /><br />
	(4) the manner of financing the agreement and establishing and maintaining the budget of the agreement;<br /><br />
	(5) the method to be employed in accomplishing the partial or complete termination of the agreement and for disposing of property upon a partial or complete termination;<br /><br />
	(6) provision for administering the agreement, which may include creation of a joint board responsible for its administration;<br /><br />
	(7) the manner of acquiring, holding, and disposing of real and personal property used in the agreement;<br /><br />
	(8) the minimum standards for National Guard personnel implementing the provisions of this agreement;<br /><br />
	(9) the minimum insurance required of each party to the agreement;<br /><br />
	(10) the chain of command or delegation of authority to be followed by National Guard personnel acting under the provisions of the agreement;<br /><br />
	(11) the duties and authority that the National Guard personnel of each party state may exercise; and<br /><br />
	(12) other necessary and proper matters.<br /><br />
	(G) As a condition precedent to an agreement becoming effective, the agreement must be submitted to and receive the approval of the Office of the Attorney General of South Carolina. The Attorney General may delegate his approval authority to the appropriate attorney for the South Carolina National Guard subject to those conditions which he decides are appropriate. The delegation must be in writing and:<br /><br />
	(1) the Attorney General, or his agent in the South Carolina National Guard, shall approve an agreement submitted to him under this provision unless he finds that it is not in proper form, does not meet the requirements set forth in this provision, or does not conform to the laws of South Carolina. If the Attorney General disapproves an agreement, he shall provide a written explanation to the Adjutant General of the National Guard;<br /><br />
	(2) if the Attorney General, or his authorized agent, approves an agreement within thirty days after its submission to him, it is considered approved by him;<br /><br />
	(3) whenever National Guard forces of a party state are engaged in drug interdiction, counterdrug activities, and demand reduction activities, they personally must not be held liable for an act or omission which occurs during the performance of their duty.<br /><br />
<div style="text-align: center;">ARTICLE IV</div>
<div style="text-align: center;">Responsibilities</div><br />
	(A) Nothing in this compact may be construed as a waiver of benefits, privileges, immunities, or rights provided for National Guard personnel performing duty pursuant to Title 32 of the United States Code, nor shall anything in this compact be construed as a waiver of coverage provided for under the Federal Tort Claims Act. If National Guard personnel performing counterdrug activities do not receive rights, benefits, privileges, and immunities provided for National Guard personnel provided in this section, then the following provisions apply:<br /><br />
	(1) Whenever National Guard forces of a responding state are engaged in another state in carrying out the purposes of this compact, the members engaged shall have the same powers, duties, rights, privileges, and immunities as members of the National Guard forces of the requesting state. The requesting state shall save and hold members of the National Guard forces of the responding state harmless from civil liability for acts or omissions which occur in the performance of their duty while engaged in carrying out the purposes of this compact, whether responding forces are serving the requesting state within the borders of the responding state or are attached to the requesting state for purposes of operational control.<br /><br />
	(2) Subject to the provisions of items (3), (4), and (5) of this subsection, liability that may arise under the laws of the requesting state or the responding states, on account of or in connection with a request for assistance or support, must be assumed and borne by the requesting state.<br /><br />
	(3) A requesting state rendering aid or assistance pursuant to this compact must be reimbursed by the requesting state for loss or damage to, or expense incurred in the operation of, equipment answering a request for aid, and for the cost of the materials, transportation, and maintenance of National Guard personnel and equipment incurred in connection with the request, provided that nothing contained in this provision prevents a responding state from assuming the loss, damage, expense, or other cost.<br /><br />
	(4) Unless there is a written agreement to the contrary, each party shall provide, in the same amounts and manner as if they were on duty within their state, for pay and allowances of the personnel of its National Guard units while engaged in another state pursuant to this compact and while going to and returning from duty pursuant to this compact.<br /><br />
	(5) Each party state providing the payment of compensation and death benefits to injured members and the representatives of deceased members of its National Guard forces in case the members sustain injuries or are killed within their own state shall provide for the payment of compensation and death benefits in the same manner and on the same terms in the event the members sustain injury or are killed while rendering assistance or support pursuant to this compact. These benefits and compensation are expense items reimbursable pursuant to item (3) of this subsection.<br /><br />
	(B) Officers and enlisted personnel of the National Guard performing duties pursuant to this compact must be subject to and governed by the provisions of their home state&#39;s Code of Military Justice whether they are performing duties within or outside their home state. If a National Guard member commits, or is suspected of committing, a criminal offense while performing duties pursuant to this compact outside his home state, he may be returned immediately to his home state and that state must be responsible for disciplinary action. However, nothing in this section abrogates the general criminal jurisdiction of the state in which the offense occurred.<br /><br />
<div style="text-align: center;">ARTICLE V</div>
<div style="text-align: center;">Delegation</div><br />
	Nothing in this compact must be construed to prevent the governor of a party state from delegating his responsibilities or authority respecting the National Guard, provided that this delegation is in accordance with law. For purposes of this compact, however, the Governor shall not delegate the power to request assistance from another state.<br /><br />
<div style="text-align: center;">ARTICLE VI</div>
<div style="text-align: center;">Limitations</div><br />
	Nothing in this compact shall:<br /><br />
	(1) authorize or permit National Guard units or personnel to be placed under the operational control of a person not having the National Guard rank or status required by law for the command in question; or<br /><br />
	(2) deprive a properly convened court of jurisdiction over an offense or a defendant because the National Guard, while performing duties pursuant to this compact, was utilized in achieving an arrest or indictment.<br /><br />
<div style="text-align: center;">ARTICLE VII</div>
<div style="text-align: center;">Construction and Severability</div><br />
	This compact must be liberally construed to effectuate its purpose. The provisions of this compact are severable and if a phrase, clause, sentence, or provision of this compact is declared to be contrary to the Constitution of the United States or of a state or its applicability to any government, agency, person, or circumstance is held invalid, the validity of the remainder of this compact and its applicability to any government, agency, person, or circumstance must not be affected. If this compact is held contrary to the Constitution of a participating state, the compact shall remain in full force and effect upon the remaining party state and in full force and effect upon the state affected as to all severable matters.<br /><br />
HISTORY: 1995 Act No. 113, SECTION 2.<br /><br />
<div style="text-align: center;">ARTICLE 9</div>
<div style="text-align: center;">Lieutenant Governor</div><br />
<span style="font-weight: bold;"> SECTION 1-3-610.</span> Compensation.<br /><br />
	The Lieutenant Governor shall receive such annual salary as may be provided by the General Assembly.<br /><br />
HISTORY: 1962 Code SECTION 1-131; 1952 Code SECTION 1-131; 1942 Code SECTION 3100; 1932 Code SECTION 3100; Civ. C. &#39;22 SECTION 782; Civ. C. &#39;12 SECTION 698; Civ. C. &#39;02 SECTION 627; G. S. 481; R. S. 544; 1865 (13) 350; 1868 (14) 135; 1871 (15) 531; 1878 (16) 246; 1893 (21) 416; 1919 (31) 4; 1924 (33) 1182; 1966 (54) 2424; Const. 1895, Art. 3 SECTIONS 2, 5-9, 13, 20; 1969 (56) 444; 1973 (58) 623.<br /><br />
<span style="font-weight: bold;"> SECTION 1-3-620.</span> Office of Lieutenant Governor to be part-time.<br /><br />
	Beginning with the term of the Lieutenant Governor elected in 1982, the duties of such office shall be part-time.<br /><br />
HISTORY: 1981 Act No. 178, Part II, SECTION 22.<br /><br />

</div>


					</div>		 <!-- mainwidepanel -->
					
				</div>		 <!-- pagebody -->
				
				<div id="footer" class="nodisplay" style="height: 30px;" onContextMenu="return false;">
			<div id="footerdiv" style="margin:0;">
				South Carolina Legislative Services Agency * 223 Blatt Building * 1105 Pendleton Street * Columbia, SC 29201<!-- * 803-212-4420--><br>
				
								<a href="/disclaimer.php">Disclaimer</a> * <a href="/policies.php">Policies</a> * <a href="/credits.php">Photo Credits</a> * <a href="/contact.php">Contact Us</a>
							</div>
		</div>
		<div id="printfooter" class="printdisplay serifNormal" align=center style="font-size: 8pt;">
			<br>
			<br>
			<hr>
			Legislative Services Agency
			<br>
			h t t p : / / w w w . s c s t a t e h o u s e . g o v
		</div>
	
		</div>	<!-- container or main in mobile page-->
</body>
</html>

