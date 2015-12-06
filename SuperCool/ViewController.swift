//
//  ViewController.swift
//  SuperCool
//
//  Created by Erol Akarsu on 06/12/2015.
//  Copyright © 2015 Erol Akarsu. All rights reserved.
//

import UIKit

class ViewController: UIViewController {

    @IBOutlet weak var coolLogo: UIImageView!
    @IBOutlet weak var coolBg: UIImageView!
    @IBOutlet weak var uncollButton: UIButton!
    
    override func viewDidLoad() {
        super.viewDidLoad()
        // Do any additional setup after loading the view, typically from a nib.
    }

    override func didReceiveMemoryWarning() {
        super.didReceiveMemoryWarning()
        // Dispose of any resources that can be recreated.
    }

    @IBAction func makeMeNotSoCool(sender: AnyObject) {
        coolLogo.hidden=false
        coolBg.hidden=false
        uncollButton.hidden=true
    }

}

