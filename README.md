# kiquja's nicotine+ plugins! ≽(•⩊ •マ≼
this is the directory for all the plugins ive made for soulseek client nicotine+. all made with AI assistance for both learning (I am beginner) & writing the code, i am also relearning how to use Github, so expect the repo to get fucked up randomly..

thanks for checking out my stuff! ᓚ₍つ^. .^₎っ♡ 



## chatwatcher - this plugin has 3 features;
### shitlist - personal moderation tool

- adds a tab that tracks keywords; how many times they where said and when they where last said.
- manual and automatic mode.
- can whitelist users.

this is my baby of the bunch. not to get all emotional but as a black and trans person online i am constantly exposed to the most fucked up language towards people like me. i love soulseek, and want it to feel a little less hostile so i made this. /ᐠﹷ ‸ ﹷ ᐟ\\ﾉ

SOON TO ADD:
- make the text fields where the user inputs usernames and keywords a bit longer (vertically) and make the divider between the log view and the settings resizable (can reference ebehavior from the userlist editor plugin in the workspace folder)
-for "shitlisted users" field, make it so CTRL F works and highlights stuff in there 
- slur counter should be treated as a filter in a drop down menu form next to the import log button, the options will be "most triggers" and "most recent" and "no filter" 
- make it so that users can be selected in the slur counter, amnd have the same context menu options as when selecting users in the log 
- add options in the plugin menu accessed by the base nicotine settings , for thre to be no GUI and only controlled by chat commands for all features. for this mode there is - no log view, for the user to see what they have applied they type /chatwatcher list and it'll list the last ~10 lines of the current shitlist log and the current keywords that get logged when used, and white listed users.
- chat tabs dont seem to remember their position when the user restarts the program
- shitlisted users field needs an update view button
- for the CTRL -F field when viewing the log, needs options to only show entries that match(live in current build already) or to highlight them all (was live in previous builds, so just make the features co-exist)
- new options for the slur counter, to add a cap on the amount of flags before person is shitlisted. ex: person has been flaged 20x = banned. flagged 10x - user has !!! nxt to name to show current standig. both values are customizable..
- !!compatibility bug tht i cant recreate right now needs fixing

### played - see what other people are listening to

- grabs /now's from #public and puts them in a tab.
- can hide users from this tab.
- however, because /now's are actually /me's, non music /me's will get thrown in there as well
- [there is settings to deal with this for now](https://lewd.pics/p/?i=nCcV.png)

this is a bit of a fringe idea but i thought it would be cool, and add a bit of personality.

### keywords - see who's talking about what! and when...
this is mostly because i am a fiend for drama, and conceited. but this can be used for many things, like knowing when to jump into the conversation when someone is talking about your famous artist.

SOON TO ADD:
- add feature to right click in played pane's context menu for entries to add user to the "hide" list (do not show in /played) and add to ban+ignore list (hard, not soft for both)
- add all settings into the right side of their corresponding feature's pane
- remove any text inside the fields boxes and add it to their options section, it being inside the box makes the UI feel cluttered
- add longer options to keep logs, 1 month and forever
- add context menu option for entries to move the UI to the room the message was said in to all panes

## theme customizer
[see it in action](https://imgur.com/a/nicotine-theme-plugin-theme-examples-feature-usage-lGUNR7X)
- gif backgrounds
- image effects (currently affects the entire window though lol
- save, import and export theme presets
- program-wide text outline
probably the most polished, but still some major flaws. i made this with the goal of accessibility, but making a swagged out theme is always fun too so any requests for features are welcome >⩊<

SOON TO ADD:
- options for text outline to just have it in some panes or text fields
  
## userlist editor
- gives the userlist-buddylist in the chatroom pane a "drawer" behavior (as in you can resize it horizontally)
- options to completely hide the userlist & buddylist.

SOON TO ADD:
- userlist visible in all panes (like how buddy list has that option in base nicotine).

## quality of life

- keybinds with conflict detection,
- context menu option on the log that allows you to export the full log anywhere,
- /rpl command that refreshes your plugins list, UI and disables and re-enables all plugins.

## page doll (currently not working)
an idea taken from the good ol' days of tumblr, a transparent image anywhere you want. back then, it was usually an anime girl but it can be anything hah. can't get it to work though... feel free to inspect it.

